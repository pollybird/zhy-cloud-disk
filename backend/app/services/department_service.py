"""部门管理业务逻辑：无限级树 CRUD、成员管理、部门树查询。"""
from datetime import datetime, timezone

from sqlalchemy import or_

from ..extensions import db
from ..models.department import Department, DepartmentAdmin, DepartmentMember
from ..models.file_permission import FilePermission
from ..models.user import User
from ..utils.errors import ApiError
from . import log_service

DEPT_NAME_MAX = 128


# ---------------------------------------------------------------------------
# 权限校验
# ---------------------------------------------------------------------------

def is_super_admin(user: User) -> bool:
    return user.role == "admin"


def _get_dept(dept_id: int) -> Department:
    dept = db.session.get(Department, int(dept_id))
    if dept is None:
        raise ApiError("部门不存在", code=3301, http_status=404)
    return dept


def can_manage_department(dept_id: int, user: User) -> bool:
    """用户是否有权管理部门（超管或本部门/祖先部门管理员 scope=self_and_sub）。"""
    if is_super_admin(user):
        return True
    # 检查用户是否是本部门或祖先部门的管理员（scope=self_and_sub）
    dept = db.session.get(Department, int(dept_id))
    if dept is None:
        return False
    while dept is not None:
        admin = (
            db.session.query(DepartmentAdmin)
            .filter(
                DepartmentAdmin.department_id == dept.id,
                DepartmentAdmin.user_id == user.id,
            )
            .first()
        )
        if admin is not None:
            if admin.scope == "self_and_sub":
                return True
            # scope=self 仅能管本部门
            return dept.id == int(dept_id)
        dept = db.session.get(Department, dept.parent_id) if dept.parent_id else None
    return False


def _require_manage(dept_id: int, user: User) -> None:
    if not can_manage_department(dept_id, user):
        raise ApiError("无权管理该部门", code=3302, http_status=403)


# ---------------------------------------------------------------------------
# 部门 CRUD
# ---------------------------------------------------------------------------

def validate_dept_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ApiError("部门名称不能为空", code=3303)
    if len(name) > DEPT_NAME_MAX:
        raise ApiError("部门名称过长", code=3303)
    return name


def create_department(name: str, parent_id: int | None, user: User) -> Department:
    name = validate_dept_name(name)
    if parent_id:
        parent = _get_dept(parent_id)
        _require_manage(parent.id, user)
        # 同级不重名
        existing = (
            db.session.query(Department)
            .filter(
                Department.parent_id == parent_id,
                Department.name == name,
                Department.status == "active",
            )
            .first()
        )
        if existing:
            raise ApiError("同级已存在同名部门", code=3304, http_status=409)
    else:
        # 根部门仅超管可建
        if not is_super_admin(user):
            raise ApiError("仅超级管理员可创建根部门", code=3302, http_status=403)

    dept = Department(
        name=name,
        parent_id=parent_id or None,
        created_by=user.id,
    )
    db.session.add(dept)
    db.session.commit()
    return dept


def update_department(
    dept_id: int,
    name: str | None,
    sort_order: int | None,
    user: User,
    storage_quota: int | None = None,
) -> Department:
    dept = _get_dept(dept_id)
    _require_manage(dept.id, user)
    old_name = dept.name
    old_quota = dept.storage_quota
    if name is not None:
        dept.name = validate_dept_name(name)
    if sort_order is not None:
        dept.sort_order = int(sort_order)
    if storage_quota is not None:
        # 配额仅超级管理员可分配；部门管理员可查看但不可修改
        if not is_super_admin(user):
            raise ApiError("仅超级管理员可调整部门配额", code=3305, http_status=403)
        quota = int(storage_quota)
        if quota < 0:
            raise ApiError("部门配额不能为负数", code=3306)
        if quota and quota < dept.used_storage:
            raise ApiError("配额不能低于当前已用空间", code=3306)
        dept.storage_quota = quota
    db.session.commit()
    log_service.record(
        user.id, "department_update", "department", dept.id, dept.id,
        {
            "old_name": old_name, "name": dept.name,
            "sort_order": dept.sort_order,
            "old_quota": old_quota, "quota": dept.storage_quota,
        },
    )
    return dept


def delete_department(dept_id: int, user: User) -> None:
    dept = _get_dept(dept_id)
    # 仅超管或本部门管理员可删
    _require_manage(dept.id, user)
    # 递归收集子孙
    ids = _subtree_dept_ids(dept.id)

    # 非空保护：部门（含子孙）下仍有正常文件/文件夹时拒绝删除，
    # 避免产生孤儿文件（SQLite 默认不启用外键约束，CASCADE 不生效；
    # 且自增主键可能被复用导致孤儿文件在新部门"复活"）。
    from ..models.file_node import FileNode

    occupied = (
        db.session.query(FileNode.id)
        .filter(
            FileNode.department_id.in_(ids),
            FileNode.status == "normal",
        )
        .limit(1)
        .first()
    )
    if occupied is not None:
        raise ApiError(
            "部门下仍有文件或文件夹，请先迁移或清空后再删除",
            code=3310,
            http_status=409,
        )

    dept_name = dept.name
    dept_id_value = dept.id
    # 显式清理成员/管理员/权限关联（不依赖数据库外键 CASCADE，兼容各数据库）
    db.session.query(DepartmentMember).filter(
        DepartmentMember.department_id.in_(ids)
    ).delete(synchronize_session=False)
    db.session.query(DepartmentAdmin).filter(
        DepartmentAdmin.department_id.in_(ids)
    ).delete(synchronize_session=False)
    db.session.query(FilePermission).filter(
        FilePermission.department_id.in_(ids)
    ).delete(synchronize_session=False)
    db.session.query(Department).filter(Department.id.in_(ids)).delete(
        synchronize_session=False
    )
    db.session.commit()
    log_service.record(
        user.id, "department_delete", "department", dept_id_value, dept_id_value,
        {"name": dept_name, "deleted_ids": sorted(ids)},
    )


def move_department(dept_id: int, new_parent_id: int | None, user: User) -> Department:
    dept = _get_dept(dept_id)
    if not is_super_admin(user):
        raise ApiError("仅超级管理员可迁移部门", code=3302, http_status=403)
    if new_parent_id:
        new_parent = _get_dept(new_parent_id)
        # 防止移到自身或子孙下
        subtree = _subtree_dept_ids(dept.id)
        if new_parent.id in subtree:
            raise ApiError("不能将部门移动到自身或其子部门下", code=3305, http_status=409)
    old_parent_id = dept.parent_id
    dept.parent_id = new_parent_id or None
    db.session.commit()
    log_service.record(
        user.id, "department_move", "department", dept.id, dept.id,
        {"name": dept.name, "old_parent_id": old_parent_id, "new_parent_id": dept.parent_id},
    )
    return dept


# ---------------------------------------------------------------------------
# 部门树查询
# ---------------------------------------------------------------------------

def get_department_tree(user: User) -> list[dict]:
    """获取用户可见的部门树。

    超管/部门管理员可见管辖范围；普通用户可见所属部门及祖先链。
    """
    all_depts = (
        db.session.query(Department)
        .filter(Department.status == "active")
        .order_by(Department.sort_order.asc(), Department.id.asc())
        .all()
    )

    if is_super_admin(user):
        visible_ids = {d.id for d in all_depts}
    else:
        # 用户管理的部门及子部门
        admin_depts = (
            db.session.query(DepartmentAdmin)
            .filter(DepartmentAdmin.user_id == user.id)
            .all()
        )
        visible_ids = set()
        for a in admin_depts:
            visible_ids.add(a.department_id)
            if a.scope == "self_and_sub":
                visible_ids |= _subtree_dept_ids(a.department_id)
        # 用户所属部门及祖先链
        members = (
            db.session.query(DepartmentMember)
            .filter(DepartmentMember.user_id == user.id)
            .all()
        )
        for m in members:
            visible_ids.add(m.department_id)
            # 向上找祖先
            dept = db.session.get(Department, m.department_id)
            while dept and dept.parent_id:
                visible_ids.add(dept.parent_id)
                dept = db.session.get(Department, dept.parent_id)
        # 有未过期显式授权（read_only/read_write）的部门，即使非成员也可见；
        # 仅被 denied 的部门不暴露，避免泄露部门存在性
        now = datetime.now(timezone.utc)
        grant_rows = (
            db.session.query(FilePermission.department_id)
            .filter(
                FilePermission.user_id == user.id,
                FilePermission.department_id.isnot(None),
                FilePermission.permission.in_(["read_only", "read_write"]),
                or_(
                    FilePermission.expire_time.is_(None),
                    FilePermission.expire_time > now,
                ),
            )
            .all()
        )
        for (dept_pk,) in grant_rows:
            visible_ids.add(dept_pk)

    # 延迟导入避免循环依赖
    from . import permission_service

    # 构建树
    children_map: dict[int | None, list] = {}
    for d in all_depts:
        if d.id not in visible_ids:
            continue
        children_map.setdefault(d.parent_id, []).append(d)

    def build_node(dept: Department) -> dict:
        data = dept.to_dict()
        data["my_permission"] = permission_service.effective_department_permission(
            user, dept.id
        )
        data["children"] = [
            build_node(c) for c in children_map.get(dept.id, [])
        ]
        return data

    roots = children_map.get(None, [])
    return [build_node(d) for d in roots]


def get_department(dept_id: int, user: User) -> dict:
    dept = _get_dept(dept_id)
    return dept.to_dict()


def _subtree_dept_ids(root_id: int) -> set[int]:
    """含根在内的全部子孙部门 ID（逐层查询）。"""
    ids = {root_id}
    frontier = [root_id]
    while frontier:
        children = [
            row[0]
            for row in db.session.query(Department.id)
            .filter(
                Department.parent_id.in_(frontier),
                Department.status == "active",
            )
            .all()
        ]
        if not children:
            break
        ids.update(children)
        frontier = children
    return ids


# ---------------------------------------------------------------------------
# 成员管理
# ---------------------------------------------------------------------------

def get_members(dept_id: int, user: User) -> list[dict]:
    _get_dept(dept_id)
    _require_manage(dept_id, user)
    rows = (
        db.session.query(DepartmentMember, User)
        .join(User, DepartmentMember.user_id == User.id)
        .filter(DepartmentMember.department_id == dept_id)
        .order_by(DepartmentMember.join_time.asc())
        .all()
    )
    result = []
    for member, u in rows:
        result.append({
            **member.to_dict(),
            "username": u.username,
            "email": u.email,
            "role": u.role,
            "status": u.status,
        })
    return result


def add_member(dept_id: int, user_id: int, position: str, user: User) -> DepartmentMember:
    _get_dept(dept_id)
    _require_manage(dept_id, user)
    target_user = db.session.get(User, int(user_id))
    if target_user is None:
        raise ApiError("用户不存在", code=3306, http_status=404)
    if target_user.status != "active":
        raise ApiError("用户已被禁用", code=3307)
    existing = (
        db.session.query(DepartmentMember)
        .filter(
            DepartmentMember.department_id == dept_id,
            DepartmentMember.user_id == user_id,
        )
        .first()
    )
    if existing:
        raise ApiError("该用户已是部门成员", code=3308, http_status=409)
    member = DepartmentMember(
        department_id=dept_id,
        user_id=user_id,
        position=position or "",
    )
    db.session.add(member)
    db.session.commit()
    log_service.record(
        user.id, "member_add", "user", user_id, dept_id,
        {"position": member.position, "member_name": target_user.username},
    )
    return member


def remove_member(dept_id: int, user_id: int, user: User) -> None:
    _get_dept(dept_id)
    _require_manage(dept_id, user)
    member = (
        db.session.query(DepartmentMember)
        .filter(
            DepartmentMember.department_id == dept_id,
            DepartmentMember.user_id == user_id,
        )
        .first()
    )
    if member is None:
        raise ApiError("该用户不是部门成员", code=3309, http_status=404)
    target_user = db.session.get(User, user_id)
    db.session.delete(member)
    db.session.commit()
    log_service.record(
        user.id, "member_remove", "user", user_id, dept_id,
        {"member_name": target_user.username if target_user else None},
    )


def update_member(
    dept_id: int, user_id: int, position: str | None, user: User
) -> DepartmentMember:
    _get_dept(dept_id)
    _require_manage(dept_id, user)
    member = (
        db.session.query(DepartmentMember)
        .filter(
            DepartmentMember.department_id == dept_id,
            DepartmentMember.user_id == user_id,
        )
        .first()
    )
    if member is None:
        raise ApiError("该用户不是部门成员", code=3309, http_status=404)
    old_position = member.position
    if position is not None:
        member.position = position
    db.session.commit()
    log_service.record(
        user.id, "member_update", "user", user_id, dept_id,
        {"old_position": old_position, "position": member.position},
    )
    return member


def get_candidate_users(
    dept_id: int, keyword: str | None, user: User
) -> list[dict]:
    """可添加为部门成员的用户候选（排除已是成员者，最多 20 条）。"""
    _get_dept(dept_id)
    _require_manage(dept_id, user)
    query = db.session.query(User).filter(User.status == "active")
    if keyword:
        pattern = f"%{keyword}%"
        query = query.filter(or_(User.username.like(pattern), User.email.like(pattern)))
    existing = db.session.query(DepartmentMember.user_id).filter(
        DepartmentMember.department_id == dept_id
    )
    query = query.filter(~User.id.in_(existing))
    rows = query.order_by(User.id.asc()).limit(20).all()
    return [{"id": u.id, "username": u.username, "email": u.email} for u in rows]
