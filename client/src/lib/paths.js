/**
 * 路径映射：服务端 parent_id 树 ↔ 本地路径双向映射。
 * 根目录（parent_id=null）映射到本地同步根目录。
 */
import path from 'path'
import { getRemoteNode } from './mirror/mirror-db.js'

/**
 * 根据服务端 parent_id 和 file_name，计算对应的本地绝对路径。
 */
export function serverPathToLocal(syncRoot, parentId, fileName) {
  if (parentId == null) {
    return path.join(syncRoot, fileName)
  }
  const parent = getRemoteNode(parentId)
  if (parent && parent.local_path) {
    return path.join(parent.local_path, fileName)
  }
  // 退化：直接挂到根目录下
  return path.join(syncRoot, fileName)
}

/**
 * 根据本地路径查找对应的服务端 id。
 */
export function localPathToServerId(localPath) {
  // 先查 remote_nodes
  const remote = getRemoteNodeByPath(localPath)
  if (remote) return remote.id
  // 再查 local_state
  const state = getLocalState(localPath)
  if (state && state.server_id) return state.server_id
  return null
}

/**
 * 根据本地父目录路径，查找对应的服务端 parent_id。
 */
export function localParentToServerId(syncRoot, localParentPath) {
  if (path.normalize(localParentPath) === path.normalize(syncRoot)) {
    return null // 根目录对应 parent_id=null
  }
  return localPathToServerId(localParentPath)
}

// 需要 import getRemoteNodeByPath 和 getLocalState
import { getRemoteNodeByPath } from './mirror/mirror-db.js'
import { getLocalState } from './mirror/mirror-db.js'
