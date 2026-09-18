"""1.2.0：跨用户秒传、blob 引用计数、分片断点续传、Range、GC 与 adopt。

使用 conftest 的 session 级已安装应用与 testuser1/testuser2，
各测试使用唯一文件名避免共享库相互干扰。
"""
import hashlib
import os
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import pytest

from app.extensions import db
from app.models.file_blob import FileBlob
from app.models.upload_session import UploadSession
from app.models.user import User
from app.services import storage_service
from app.tasks import blob_adopt, upload_cleanup


def md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def upload_file(client, headers, name, content, extra=None):
    form = {"files": (BytesIO(content), name)}
    if extra:
        form.update(extra)
    return client.post(
        "/api/file/upload", data=form, headers=headers, content_type="multipart/form-data"
    )


def instant(client, headers, name, content):
    return client.post(
        "/api/file/instant",
        json={
            "file_name": name,
            "file_size": len(content),
            "file_hash": md5(content),
        },
        headers=headers,
    )


def blob_files(app) -> list[Path]:
    root = Path(app.config["STORAGE_DIR"]) / "blobs"
    return [p for p in root.glob("*/*") if p.is_file()] if root.exists() else []


# ---------------------------------------------------------------------------
# 跨用户秒传与引用计数
# ---------------------------------------------------------------------------

def test_cross_user_instant_shares_physical(app, client, user_headers, user2_headers):
    tag = uuid.uuid4().hex[:8]
    content = f"shared-content-{tag}".encode() * 100
    name1, name2 = f"{tag}_a.txt", f"{tag}_b.txt"

    r = upload_file(client, user_headers, name1, content, {"file_hash": md5(content)})
    assert r.status_code == 200
    node1 = r.get_json()["data"]["success"][0]

    r = instant(client, user2_headers, name2, content)
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["instant"] is True and data["skipped"] is False
    node2 = data["node"]
    assert node2["id"] != node1["id"]

    # 物理文件只有一份，引用计数为 2
    blobs = [p for p in blob_files(app) if p.name == md5(content)]
    assert len(blobs) == 1
    with app.app_context():
        blob = db.session.query(FileBlob).filter_by(file_hash=md5(content)).first()
        assert blob.ref_count == 2
        # 双方配额都按逻辑扣减
        u1 = db.session.query(User).filter_by(username="testuser1").first()
        u2 = db.session.query(User).filter_by(username="testuser2").first()
        assert u1.used_storage >= len(content)
        assert u2.used_storage >= len(content)

    # 双方都能下载到一致内容
    for headers, nid in ((user_headers, node1["id"]), (user2_headers, node2["id"])):
        r = client.get(f"/api/file/download?id={nid}", headers=headers)
        assert r.data == content


def test_instant_miss_returns_false(client, user2_headers):
    content = f"never-uploaded-{uuid.uuid4().hex}".encode()
    r = instant(client, user2_headers, "miss.txt", content)
    assert r.get_json()["data"] == {"instant": False}


def test_instant_same_name_same_hash_is_skip(app, client, user_headers, user2_headers):
    tag = uuid.uuid4().hex[:8]
    content = f"skip-content-{tag}".encode() * 10
    name = f"{tag}_same.txt"
    upload_file(client, user_headers, name, content, {"file_hash": md5(content)})
    # user2 先秒传到自己空间
    instant(client, user2_headers, name, content)
    with app.app_context():
        before = (
            db.session.query(User).filter_by(username="testuser2").first().used_storage
        )
    # 同目录同名同 hash 再秒传 → skipped，不重复扣配额
    r = instant(client, user2_headers, name, content)
    data = r.get_json()["data"]
    assert data["instant"] is True and data["skipped"] is True
    with app.app_context():
        after = db.session.query(User).filter_by(username="testuser2").first().used_storage
    assert after == before


def test_instant_quota_rejected(app, client, user_headers, user2_headers):
    tag = uuid.uuid4().hex[:8]
    content = f"quota-content-{tag}".encode() * 50
    upload_file(client, user_headers, f"{tag}_src.txt", content,
                {"file_hash": md5(content)})

    with app.app_context():
        u = db.session.query(User).filter_by(username="testuser2").first()
        original = u.total_storage
        u.total_storage = 0
        db.session.commit()
    try:
        r = instant(client, user2_headers, f"{tag}_noquota.txt", content)
        assert r.status_code == 413
        assert r.get_json()["code"] == 3106
    finally:
        with app.app_context():
            u = db.session.query(User).filter_by(username="testuser2").first()
            u.total_storage = original
            db.session.commit()


def test_delete_shared_blob_keeps_other_copy(app, client, user_headers, user2_headers):
    tag = uuid.uuid4().hex[:8]
    content = f"delete-content-{tag}".encode() * 100
    h = md5(content)
    r = upload_file(client, user_headers, f"{tag}_a.txt", content, {"file_hash": h})
    id1 = r.get_json()["data"]["success"][0]["id"]
    id2 = instant(client, user2_headers, f"{tag}_b.txt", content).get_json()["data"]["node"]["id"]

    client.delete(f"/api/file/delete", json={"id": id1}, headers=user_headers)
    # user2 的副本仍可下载，blob 仍在，计数为 1
    assert client.get(f"/api/file/download?id={id2}", headers=user2_headers).data == content
    with app.app_context():
        blob = db.session.query(FileBlob).filter_by(file_hash=h).first()
        assert blob is not None and blob.ref_count == 1

    client.delete(f"/api/file/delete", json={"id": id2}, headers=user2_headers)
    with app.app_context():
        assert db.session.query(FileBlob).filter_by(file_hash=h).first() is None
    assert not [p for p in blob_files(app) if p.name == h]


def test_overwrite_same_content_keeps_blob(app, client, user_headers):
    tag = uuid.uuid4().hex[:8]
    content = f"ow-content-{tag}".encode() * 30
    h = md5(content)
    r = upload_file(client, user_headers, f"{tag}_ow.txt", content, {"file_hash": h})
    nid = r.get_json()["data"]["success"][0]["id"]
    # 用同样内容覆盖（mode=overwrite）：净计数不变、物理文件保留
    r = upload_file(
        client, user_headers, f"{tag}_ow.txt", content,
        {"file_hash": h, "mode": "overwrite", "overwrite_id": str(nid)},
    )
    assert r.get_json()["data"]["success"]
    with app.app_context():
        blob = db.session.query(FileBlob).filter_by(file_hash=h).first()
        assert blob is not None and blob.ref_count == 1
    assert client.get(f"/api/file/download?id={nid}", headers=user_headers).data == content


# ---------------------------------------------------------------------------
# 分片上传 / 断点续传
# ---------------------------------------------------------------------------

def _chunked_content(seed: str, size: int) -> bytes:
    return hashlib.sha256(seed.encode()).digest() * (size // 32 + 1)


def test_chunk_full_flow_and_range(app, client, user_headers):
    tag = uuid.uuid4().hex[:8]
    size = 2 * 1024 * 1024 + 123  # 3 个分片，末片非满
    content = _chunked_content(tag, size)[:size]
    h = md5(content)
    chunk_size = 1024 * 1024

    r = client.post("/api/file/chunk/init", json={
        "file_name": f"{tag}_big.bin", "file_size": size,
        "file_hash": h, "chunk_size": chunk_size,
    }, headers=user_headers)
    init = r.get_json()["data"]
    assert init["instant"] is False
    assert init["total_chunks"] == 3
    upload_id = init["upload_id"]

    # 乱序上传：先 0 和 2
    for idx in (0, 2):
        start = idx * chunk_size
        part = content[start:start + chunk_size]
        r = client.post("/api/file/chunk/upload", data={
            "upload_id": upload_id, "index": str(idx),
            "chunk_hash": md5(part), "chunk": (BytesIO(part), f"{idx}.part"),
        }, headers=user_headers, content_type="multipart/form-data")
        assert r.status_code == 200

    # status 反映已收分片
    r = client.get(f"/api/file/chunk/status?upload_id={upload_id}", headers=user_headers)
    assert r.get_json()["data"]["received"] == [0, 2]

    # 缺片 complete 被拒
    r = client.post("/api/file/chunk/complete", json={"upload_id": upload_id},
                    headers=user_headers)
    assert r.get_json()["code"] == 3210

    # 补齐最后一片
    part = content[chunk_size:2 * chunk_size]
    client.post("/api/file/chunk/upload", data={
        "upload_id": upload_id, "index": "1",
        "chunk_hash": md5(part), "chunk": (BytesIO(part), "1.part"),
    }, headers=user_headers, content_type="multipart/form-data")

    r = client.post("/api/file/chunk/complete", json={"upload_id": upload_id},
                    headers=user_headers)
    assert r.status_code == 200
    nid = r.get_json()["data"]["node"]["id"]

    # 完整下载校验
    r = client.get(f"/api/file/download?id={nid}", headers=user_headers)
    assert r.data == content

    # Range 断点下载：206 + Content-Range
    r = client.get(f"/api/file/download?id={nid}",
                   headers={**user_headers, "Range": "bytes=0-3"})
    assert r.status_code == 206
    assert r.data == content[:4]
    assert r.headers["Content-Range"] == f"bytes 0-3/{size}"

    # 会话与 tmp 目录已清理
    with app.app_context():
        assert db.session.get(UploadSession, upload_id) is None
    assert not (Path(app.config["STORAGE_DIR"]) / "tmp" / "uploads" / upload_id).exists()
    # 分片产物已进入 blob 体系
    with app.app_context():
        assert db.session.query(FileBlob).filter_by(file_hash=h).first() is not None


def test_chunk_resume_returns_received(app, client, user_headers):
    tag = uuid.uuid4().hex[:8]
    size = 1024 * 1024 + 50
    content = _chunked_content(tag, size)[:size]
    h = md5(content)
    payload = {
        "file_name": f"{tag}_resume.bin", "file_size": size,
        "file_hash": h, "chunk_size": 1024 * 1024,
    }
    r = client.post("/api/file/chunk/init", json=payload, headers=user_headers)
    upload_id = r.get_json()["data"]["upload_id"]

    part = content[:1024 * 1024]
    client.post("/api/file/chunk/upload", data={
        "upload_id": upload_id, "index": "0",
        "chunk": (BytesIO(part), "0.part"),
    }, headers=user_headers, content_type="multipart/form-data")

    # 重新 init：恢复同一会话并告知已收分片
    r = client.post("/api/file/chunk/init", json=payload, headers=user_headers)
    data = r.get_json()["data"]
    assert data["upload_id"] == upload_id and data["received"] == [0]

    # 续传剩余分片并完成
    tail = content[1024 * 1024:]
    client.post("/api/file/chunk/upload", data={
        "upload_id": upload_id, "index": "1",
        "chunk": (BytesIO(tail), "1.part"),
    }, headers=user_headers, content_type="multipart/form-data")
    r = client.post("/api/file/chunk/complete", json={"upload_id": upload_id},
                    headers=user_headers)
    assert r.status_code == 200


def test_chunk_init_instant_shortcut(client, user_headers, user2_headers):
    tag = uuid.uuid4().hex[:8]
    content = f"init-instant-{tag}".encode() * 20
    upload_file(client, user_headers, f"{tag}_src.txt", content,
                {"file_hash": md5(content)})
    r = client.post("/api/file/chunk/init", json={
        "file_name": f"{tag}_dst.txt", "file_size": len(content),
        "file_hash": md5(content), "chunk_size": 1024 * 1024,
    }, headers=user2_headers)
    assert r.get_json()["data"]["instant"] is True


def test_chunk_bad_index_and_hash(client, user_headers):
    tag = uuid.uuid4().hex[:8]
    size = 1024 * 1024
    content = _chunked_content(tag, size)[:size]
    r = client.post("/api/file/chunk/init", json={
        "file_name": f"{tag}_bad.bin", "file_size": size,
        "file_hash": md5(content), "chunk_size": size,
    }, headers=user_headers)
    upload_id = r.get_json()["data"]["upload_id"]

    # 越界序号
    r = client.post("/api/file/chunk/upload", data={
        "upload_id": upload_id, "index": "5",
        "chunk": (BytesIO(content), "0.part"),
    }, headers=user_headers, content_type="multipart/form-data")
    assert r.get_json()["code"] == 3208

    # 分片 MD5 不符
    r = client.post("/api/file/chunk/upload", data={
        "upload_id": upload_id, "index": "0", "chunk_hash": "0" * 32,
        "chunk": (BytesIO(content), "0.part"),
    }, headers=user_headers, content_type="multipart/form-data")
    assert r.get_json()["code"] == 3209


def test_chunk_abort_cleans(app, client, user_headers):
    tag = uuid.uuid4().hex[:8]
    size = 1024 * 1024
    content = _chunked_content(tag, size)[:size]
    r = client.post("/api/file/chunk/init", json={
        "file_name": f"{tag}_abort.bin", "file_size": size,
        "file_hash": md5(content), "chunk_size": size,
    }, headers=user_headers)
    upload_id = r.get_json()["data"]["upload_id"]
    client.post("/api/file/chunk/upload", data={
        "upload_id": upload_id, "index": "0",
        "chunk": (BytesIO(content), "0.part"),
    }, headers=user_headers, content_type="multipart/form-data")

    assert client.post("/api/file/chunk/abort", json={"upload_id": upload_id},
                       headers=user_headers).status_code == 200
    with app.app_context():
        assert db.session.get(UploadSession, upload_id) is None
    assert not (Path(app.config["STORAGE_DIR"]) / "tmp" / "uploads" / upload_id).exists()
    # 再操作已清理会话 → 3207
    r = client.post("/api/file/chunk/complete", json={"upload_id": upload_id},
                    headers=user_headers)
    assert r.get_json()["code"] == 3207


def test_chunk_whole_hash_mismatch(client, user_headers):
    tag = uuid.uuid4().hex[:8]
    size = 1024 * 1024
    content = _chunked_content(tag, size)[:size]
    r = client.post("/api/file/chunk/init", json={
        "file_name": f"{tag}_mismatch.bin", "file_size": size,
        "file_hash": "f" * 32, "chunk_size": size,
    }, headers=user_headers)
    upload_id = r.get_json()["data"]["upload_id"]
    client.post("/api/file/chunk/upload", data={
        "upload_id": upload_id, "index": "0",
        "chunk": (BytesIO(content), "0.part"),
    }, headers=user_headers, content_type="multipart/form-data")
    r = client.post("/api/file/chunk/complete", json={"upload_id": upload_id},
                    headers=user_headers)
    assert r.get_json()["code"] == 3205


# ---------------------------------------------------------------------------
# GC 与存量 adopt
# ---------------------------------------------------------------------------

def test_upload_cleanup_expired_and_orphan(app, client, user_headers):
    tag = uuid.uuid4().hex[:8]
    size = 1024 * 1024
    content = _chunked_content(tag, size)[:size]
    r = client.post("/api/file/chunk/init", json={
        "file_name": f"{tag}_gc.bin", "file_size": size,
        "file_hash": md5(content), "chunk_size": size,
    }, headers=user_headers)
    upload_id = r.get_json()["data"]["upload_id"]

    # 手工造孤儿目录
    orphan = Path(app.config["STORAGE_DIR"]) / "tmp" / "uploads" / ("0" * 32)
    orphan.mkdir(parents=True, exist_ok=True)
    (orphan / "00000000.part").write_bytes(b"x")

    with app.app_context():
        s = db.session.get(UploadSession, upload_id)
        s.expire_time = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.session.commit()
        stats = upload_cleanup.run()

    assert stats["expired_sessions"] >= 1
    assert stats["orphan_dirs"] >= 1
    with app.app_context():
        assert db.session.get(UploadSession, upload_id) is None
    assert not orphan.exists()


def test_blob_adopt_legacy_files(app, client, user_headers):
    tag = uuid.uuid4().hex[:8]
    content = f"legacy-adopt-{tag}".encode() * 40
    h = md5(content)
    size = len(content)
    # 正常上传一份（已在 blob 体系）
    upload_file(client, user_headers, f"{tag}_new.txt", content, {"file_hash": h})

    with app.app_context():
        from app.models.file_node import FileNode
        owner = db.session.query(User).filter_by(username="testuser1").first()
        # 手工构造 1.1 形态的遗留物理文件（user 目录、非 blob 路径、带 hash）
        user_dir = storage_service.user_dir(owner.id)
        legacy = user_dir / f"{uuid.uuid4().hex}.txt"
        legacy.write_bytes(content)
        node = FileNode(
            user_id=owner.id, department_id=None, file_name=f"{tag}_legacy.txt",
            file_suffix="txt", file_size=size, save_path=str(legacy),
            file_hash=h, is_folder=False, parent_id=None, status="normal",
        )
        db.session.add(node)
        db.session.commit()
        legacy_id = node.id
        legacy_path = str(legacy)

        stats = blob_adopt.run()
        assert stats["groups_merged"] >= 1

        refreshed = db.session.get(FileNode, legacy_id)
        assert storage_service.is_blob_path(refreshed.save_path)
        assert not Path(legacy_path).exists()
        blob = db.session.query(FileBlob).filter_by(file_hash=h).first()
        # 同一物理块被新文件与遗留文件共同引用
        assert blob.ref_count == 2
        assert blob.save_path == refreshed.save_path

    # 内容可正常下载
    r = client.get(f"/api/file/download?id={legacy_id}", headers=user_headers)
    assert r.data == content


def test_blob_adopt_hashless_backfill(app):
    from app.models.file_node import FileNode
    tag = uuid.uuid4().hex[:8]
    content = f"hashless-{tag}".encode() * 20
    h = md5(content)
    with app.app_context():
        user_dir = storage_service.user_dir(1)
        legacy = user_dir / f"{uuid.uuid4().hex}.dat"
        legacy.write_bytes(content)
        node = FileNode(
            user_id=1, department_id=None, file_name=f"{tag}_hashless.dat",
            file_suffix="dat", file_size=len(content), save_path=str(legacy),
            file_hash=None, is_folder=False, parent_id=None, status="normal",
        )
        db.session.add(node)
        db.session.commit()
        nid = node.id

        blob_adopt.run()
        # 补 hash + 并入 blob 在同一 run 的两个阶段完成
        refreshed = db.session.get(FileNode, nid)
        assert refreshed.file_hash == h
        assert storage_service.is_blob_path(refreshed.save_path)
