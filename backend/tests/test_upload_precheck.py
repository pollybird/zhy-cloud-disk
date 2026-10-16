"""M6：上传前预检——容量/并发会话数/暂存水位。"""
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.models.upload_session import UploadSession
from app.models.user import User
from app.services import file_service


def _h(tag: str) -> str:
    return hashlib.md5(f"m6-{tag}-{uuid.uuid4().hex}".encode()).hexdigest()


@pytest.fixture(autouse=True)
def _cleanup_sessions(app):
    """全局 app 数据库跨用例保留，每用例后清理本文件制造的测试会话。"""
    yield
    with app.app_context():
        db.session.query(UploadSession).filter(
            UploadSession.file_name.in_(("m6sess.bin", "m6resume.bin"))
        ).delete(synchronize_session=False)
        db.session.commit()


def _init(client, headers, tag, size=100):
    return client.post("/api/file/chunk/init", json={
        "file_name": f"{tag}.bin",
        "file_size": size,
        "file_hash": _h(tag),
        "chunk_size": 1024 * 1024,
    }, headers=headers)


def _user(app):
    with app.app_context():
        return db.session.query(User).filter(User.username == "testuser1").first()


def _add_sessions(app, user_id, count):
    now = datetime.now(timezone.utc)
    with app.app_context():
        for _ in range(count):
            h = _h(f"sess-{uuid.uuid4().hex}")
            db.session.add(UploadSession(
                id=uuid.uuid4().hex,
                user_id=user_id,
                file_name="m6sess.bin",
                file_size=100,
                file_hash=h,
                chunk_size=1024 * 1024,
                total_chunks=1,
                status="uploading",
                create_time=now,
                expire_time=now + timedelta(hours=1),
            ))
        db.session.commit()


def test_chunk_init_quota_precheck(app, client, user_headers):
    user = _user(app)
    with app.app_context():
        u = db.session.get(User, user.id)
        original_total = u.total_storage
        # 配额恰好用尽：used == total
        u.total_storage = u.used_storage
        db.session.commit()
    try:
        r = _init(client, user_headers, "over-quota", size=100)
        assert r.status_code == 413
        assert r.get_json()["code"] == 3106
    finally:
        with app.app_context():
            u = db.session.get(User, user.id)
            u.total_storage = original_total
            db.session.commit()


def test_chunk_init_active_session_limit(app, client, user_headers):
    user = _user(app)
    _add_sessions(app, user.id, file_service.MAX_ACTIVE_SESSIONS_PER_USER)
    r = _init(client, user_headers, "51st", size=100)
    assert r.status_code == 429
    assert r.get_json()["code"] == 3212


def test_chunk_init_staging_watermark(app, client, user_headers, monkeypatch):
    # 水位上限压到 1 字节：任何新分片初始化都被拒
    monkeypatch.setattr(file_service, "MAX_STAGING_BYTES", 1)
    r = _init(client, user_headers, "watermark", size=100)
    assert r.status_code == 429
    assert r.get_json()["code"] == 3213


def test_watermark_counts_real_tmp_dirs(app):
    """水位统计覆盖真实目录 storage/tmp/uploads 与 storage/tmp/staging。"""
    from pathlib import Path

    from app.services import storage_service

    with app.app_context():
        before = file_service._staging_watermark()
        uploads = storage_service.uploads_tmp_root()
        staging = storage_service.staging_dir()
        (Path(uploads) / "m6_probe_session").mkdir(exist_ok=True)
        p1 = Path(uploads) / "m6_probe_session" / "0.part"
        p2 = Path(staging) / "m6_probe_staged"
        p1.write_bytes(b"x" * 300)
        p2.write_bytes(b"y" * 200)
        try:
            assert file_service._staging_watermark() >= before + 500
        finally:
            p1.unlink(missing_ok=True)
            p2.unlink(missing_ok=True)
            (Path(uploads) / "m6_probe_session").rmdir()


def test_instant_shortcut_bypasses_session_and_watermark(
    app, client, user_headers, monkeypatch
):
    """秒传不建会话/不落暂存：会话数满 + 水位极低时仍可秒传。"""
    import io

    user = _user(app)
    tag = uuid.uuid4().hex[:8]
    content = f"m6-instant-{tag}".encode() * 10
    h = hashlib.md5(content).hexdigest()
    # 先整文件上传，制造可秒传的 blob（此时水位上限正常）
    r = client.post("/api/file/upload", headers=user_headers,
                    data={"files": (io.BytesIO(content), f"{tag}.txt")})
    assert r.status_code == 200

    # 再制造"会话数满 + 水位极低"的紧张条件
    _add_sessions(app, user.id, file_service.MAX_ACTIVE_SESSIONS_PER_USER)
    monkeypatch.setattr(file_service, "MAX_STAGING_BYTES", 1)

    r = client.post("/api/file/chunk/init", json={
        "file_name": f"{tag}_copy.txt",
        "file_size": len(content),
        "file_hash": h,
        "chunk_size": 1024 * 1024,
    }, headers=user_headers)
    assert r.status_code == 200
    assert r.get_json()["data"]["instant"] is True


def test_resumable_session_reuse_ignores_limit(app, client, user_headers):
    """断点恢复复用既有会话，不占用新会话名额。"""
    user = _user(app)
    _add_sessions(app, user.id, file_service.MAX_ACTIVE_SESSIONS_PER_USER - 1)

    h = _h("resume")
    now = datetime.now(timezone.utc)
    with app.app_context():
        existing = UploadSession(
            id=uuid.uuid4().hex,
            user_id=user.id,
            file_name="m6resume.bin",
            file_size=100,
            file_hash=h,
            chunk_size=1024 * 1024,
            total_chunks=1,
            status="uploading",
            create_time=now,
            expire_time=now + timedelta(hours=1),
        )
        db.session.add(existing)
        db.session.commit()
        existing_id = existing.id

    r = client.post("/api/file/chunk/init", json={
        "file_name": "m6resume.bin",
        "file_size": 100,
        "file_hash": h,
        "chunk_size": 1024 * 1024,
    }, headers=user_headers)
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["instant"] is False
    assert data["upload_id"] == existing_id
