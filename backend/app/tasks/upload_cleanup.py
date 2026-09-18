"""分片上传暂存区清理。

- 删除已过期（默认 24h）的上传会话与分片记录，并移除对应 tmp 目录
- 清理磁盘上无 DB 记录的孤儿会话目录（异常退出/手工残留）
"""
from datetime import datetime, timezone

from ..extensions import db
from ..models.upload_session import UploadChunk, UploadSession
from ..services import storage_service


def run() -> dict:
    """执行一轮清理，返回 {expired_sessions, orphan_dirs}。"""
    now = datetime.now(timezone.utc)
    expired = (
        db.session.query(UploadSession)
        .filter(UploadSession.expire_time < now)
        .all()
    )
    expired_ids = [s.id for s in expired]
    expired_count = 0
    for sid in expired_ids:
        db.session.query(UploadChunk).filter(
            UploadChunk.session_id == sid
        ).delete(synchronize_session=False)
        obj = db.session.get(UploadSession, sid)
        if obj is not None:
            db.session.delete(obj)
        expired_count += 1
    if expired_ids:
        db.session.commit()
        for sid in expired_ids:
            storage_service.remove_session_dir(sid)

    # 孤儿目录：磁盘存在但任何状态的会话都无记录
    if expired_ids:
        db.session.expire_all()
    known = {
        row[0] for row in db.session.query(UploadSession.id).all()
    }
    orphan = 0
    for name in storage_service.iter_session_dirs():
        if name not in known:
            storage_service.remove_session_dir(name)
            orphan += 1

    return {"expired_sessions": expired_count, "orphan_dirs": orphan}
