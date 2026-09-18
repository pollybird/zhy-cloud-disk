"""部门文件排他编辑锁业务逻辑（1.2.0）。

锁语义：
- 持有者（或部门管理员/超管）之外的用户对被锁文件的写操作（覆盖保存/改名/移动/删除）一律拒绝
- 读不受限制：其他人可下载查看，客户端以只读方式打开
- acquire 幂等：持有者重复获取视为心跳续约；TTL 过期或被管理员释放后他人可获取
- 仅部门文件可加锁；个人文件一律拒绝
"""
from datetime import datetime, timedelta, timezone

from ..extensions import db
from ..models.file_lock import FileLock
from ..models.file_node import FileNode
from ..models.user import User
from ..utils.errors import ApiError
from . import department_service
from . import permission_service

# 锁有效期：客户端每 30s 心跳；崩溃后最多 2min 自动释放
LOCK_TTL = timedelta(minutes=2)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def purge_expired(now: datetime | None = None) -> int:
    """删除全部过期锁，返回删除条数。"""
    now = now or _now()
    deleted = (
        db.session.query(FileLock)
        .filter(FileLock.expire_time <= now)
        .delete(synchronize_session=False)
    )
    if deleted:
        db.session.commit()
    return deleted


def get_active(node_id: int, now: datetime | None = None) -> FileLock | None:
    """返回有效锁；过期锁顺手清除。无锁返回 None。"""
    now = now or _now()
    lock = db.session.get(FileLock, int(node_id))
    if lock is None:
        return None
    if _as_aware(lock.expire_time) <= now:
        db.session.delete(lock)
        db.session.commit()
        return None
    return lock


def lock_map(node_ids, now: datetime | None = None) -> dict[int, FileLock]:
    """批量取有效锁（列表序列化用），先清过期再一次查询。"""
    ids = [i for i in node_ids if i is not None]
    if not ids:
        return {}
    now = now or _now()
    rows = db.session.query(FileLock).filter(FileLock.node_id.in_(ids)).all()
    out = {}
    for row in rows:
        if _as_aware(row.expire_time) > now:
            out[row.node_id] = row
    return out


def _lock_conflict(lock: FileLock) -> ApiError:
    return ApiError(
        f"文件正被「{lock.user_name}」编辑，请稍后再试",
        code=3501,
        http_status=409,
        data={"user_id": lock.user_id, "user_name": lock.user_name},
    )


def acquire(user: User, node_id: int) -> dict:
    """获取排他锁；持有者重复获取即续约。"""
    node = db.session.get(FileNode, int(node_id))
    if node is None or node.status != "normal" or node.is_folder:
        raise ApiError("文件不存在", code=3101, http_status=404)
    if node.department_id is None:
        raise ApiError("个人文件不支持编辑锁", code=3503, http_status=400)
    if not permission_service.check_file_access(user, node, "write"):
        raise ApiError("无权锁定该文件（需要读写权限）", code=4032, http_status=403)

    now = _now()
    lock = get_active(node_id, now)
    if lock is not None:
        if lock.user_id == user.id:
            # 幂等续约
            lock.renew_time = now
            lock.expire_time = now + LOCK_TTL
            db.session.commit()
            return {"locked": True, "held_by_me": True, "lock": lock.to_dict()}
        raise _lock_conflict(lock)

    lock = FileLock(
        node_id=node.id,
        user_id=user.id,
        user_name=user.username,
        create_time=now,
        renew_time=now,
        expire_time=now + LOCK_TTL,
    )
    db.session.add(lock)
    try:
        db.session.commit()
    except Exception:
        # 并发竞争：对方先插入则报冲突
        db.session.rollback()
        winner = get_active(node_id)
        if winner is not None and winner.user_id != user.id:
            raise _lock_conflict(winner)
        if winner is not None:
            return {"locked": True, "held_by_me": True, "lock": winner.to_dict()}
        raise
    return {"locked": True, "held_by_me": True, "lock": lock.to_dict()}


def renew(user: User, node_id: int) -> dict:
    """心跳续约，仅持有者可调用。"""
    lock = get_active(int(node_id))
    if lock is None:
        raise ApiError("文件未被锁定", code=3502, http_status=409)
    if lock.user_id != user.id:
        raise _lock_conflict(lock)
    now = _now()
    lock.renew_time = now
    lock.expire_time = now + LOCK_TTL
    db.session.commit()
    return {"locked": True, "held_by_me": True, "lock": lock.to_dict()}


def release(user: User, node_id: int, force: bool = False) -> dict:
    """释放锁：持有者可释放；force=True 时超管/部门管理员可强制释放。"""
    lock = get_active(int(node_id))
    if lock is None:
        return {"locked": False}
    if lock.user_id != user.id and not force:
        raise ApiError("只有锁持有者可以释放该锁", code=3502, http_status=409)
    if lock.user_id != user.id and force:
        node = db.session.get(FileNode, int(node_id))
        is_admin = (
            node is not None
            and (
                department_service.is_super_admin(user)
                or department_service.can_manage_department(node.department_id, user)
            )
        )
        if not is_admin:
            raise ApiError("无权释放他人的编辑锁", code=4032, http_status=403)
    db.session.delete(lock)
    db.session.commit()
    return {"locked": False}


def status(user: User, node_id: int) -> dict:
    """查询单个文件锁状态（打开前确认用）。"""
    node = db.session.get(FileNode, int(node_id))
    if node is None or node.status != "normal":
        raise ApiError("文件不存在", code=3101, http_status=404)
    lock = get_active(node_id)
    if lock is None:
        return {"locked": False, "held_by_me": False, "lock": None}
    return {
        "locked": True,
        "held_by_me": lock.user_id == user.id,
        "lock": lock.to_dict(),
    }


def ensure_unlocked(user: User, node: FileNode) -> None:
    """写操作守卫：部门文件被他人持锁时拒绝。持有者本人放行。"""
    if node is None or node.department_id is None or node.is_folder:
        return
    lock = get_active(node.id)
    if lock is not None and lock.user_id != user.id:
        raise _lock_conflict(lock)


def assert_no_lock_in_tree(node_ids) -> None:
    """删除文件夹前：子树内存在任意有效锁即拒绝（持有者本人也不能直接删）。"""
    ids = list(node_ids)
    if not ids:
        return
    now = _now()
    locks = (
        db.session.query(FileLock)
        .filter(
            FileLock.node_id.in_(ids),
            FileLock.expire_time > now,
        )
        .all()
    )
    if locks:
        # 提示其中一个持有者
        raise _lock_conflict(locks[0])
