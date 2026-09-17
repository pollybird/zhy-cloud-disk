/**
 * 部门树纯函数辅助（客户端部门网盘页面使用）。
 * 树节点由 GET /api/department/tree 返回，关键字段：
 *   { id, name, parent_id, children, my_permission: 'read_write'|'read_only'|'none' }
 */

/**
 * 在部门树中按 id 查找节点（深度优先）。
 * @param {Array} tree 带 children 的部门树
 * @param {number|string|null|undefined} id
 * @returns {object|null}
 */
export function findDeptNode(tree, id) {
  if (!Array.isArray(tree) || id === null || id === undefined) return null
  for (const node of tree) {
    if (node.id === id) return node
    const hit = findDeptNode(node.children, id)
    if (hit) return hit
  }
  return null
}

/**
 * 有效权限是否可写（上传 / 新建 / 重命名 / 移动 / 删除）。
 * 后端标注值：read_write / read_only / none
 * @param {string|undefined|null} access
 * @returns {boolean}
 */
export function canWrite(access) {
  return access === 'read_write'
}

/**
 * 深度优先查找第一个可访问（非 none）的部门 id。
 * @param {Array} nodes
 * @returns {number|null}
 */
export function firstReadableId(nodes) {
  for (const node of nodes || []) {
    if (node.my_permission && node.my_permission !== 'none') return node.id
    const child = firstReadableId(node.children)
    if (child) return child
  }
  return null
}

/** 权限中文标签。 */
export function permLabel(perm) {
  if (perm === 'read_write') return '读写'
  if (perm === 'read_only') return '只读'
  return '无权'
}

/** 权限对应 el-tag 类型。 */
export function permTagType(perm) {
  if (perm === 'read_write') return 'success'
  if (perm === 'read_only') return 'info'
  return 'danger'
}
