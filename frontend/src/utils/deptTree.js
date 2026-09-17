// 部门树与有效权限的纯函数辅助（部门网盘视图使用）

/**
 * 在部门树中按 id 查找节点（深度优先）。
 * @param {Array} tree 带 children 的部门树
 * @param {number|string|null} id
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
 */
export function canWrite(access) {
  return access === 'read_write'
}
