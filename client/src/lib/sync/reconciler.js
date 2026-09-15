/**
 * 协调器：对比远端快照与本地镜像，生成同步任务灌入队列。
 * 处理远端→本地下行（新增/改名/移动/内容变更/删除）和冲突。
 */
import path from 'path'
import {
  getRemoteNode,
  upsertRemoteNode,
  deleteRemoteNode,
  getAllRemoteNodes,
  getLocalState,
  deleteLocalState,
} from '../mirror/mirror-db.js'
import { serverPathToLocal } from '../paths.js'
import { warn } from '../logger.js'
import { emit, EVENTS } from '../events.js'

/**
 * 对比远端快照与镜像，生成下行同步任务。
 */
export function reconcileRemote(snapshot, syncRoot, conflictStrategy) {
  const tasks = []
  const remoteIds = new Set(snapshot.keys())
  const mirrorNodes = getAllRemoteNodes()

  // 1. 远端有、镜像中无 → 新增（下载/建目录）
  for (const [id, node] of snapshot) {
    const mirror = getRemoteNode(id)
    if (!mirror) {
      const localPath = serverPathToLocal(syncRoot, node.parent_id, node.file_name)
      if (node.is_folder) {
        tasks.push({ type: 'mkdir_local', localPath })
      } else {
        tasks.push({ type: 'download', serverId: id, localPath })
      }
      // 更新镜像
      upsertRemoteNode(node, localPath)
      continue
    }

    // 2. 远端有、镜像有 → 比对字段
    const nameChanged = mirror.file_name !== node.file_name
    const parentChanged = mirror.parent_id !== node.parent_id
    const contentChanged = node.upload_time && mirror.upload_time !== node.upload_time && mirror.file_size !== node.file_size

    if (nameChanged || parentChanged) {
      // 远端改名/移动 → 本地 rename/move
      const newLocalPath = serverPathToLocal(syncRoot, node.parent_id, node.file_name)
      tasks.push({
        type: 'move_local',
        oldPath: mirror.local_path,
        newPath: newLocalPath,
        serverId: id,
      })
      upsertRemoteNode(node, newLocalPath)
    } else if (contentChanged) {
      // 远端内容变更 → 检查本地是否也改了
      const state = getLocalState(mirror.local_path)
      const localChanged = state && state.state === 'pending_upload'
      if (localChanged) {
        // 冲突
        if (conflictStrategy === 'keep-both') {
          const ext = path.extname(node.file_name)
          const stem = path.basename(node.file_name, ext)
          const conflictPath = path.join(path.dirname(mirror.local_path), `${stem} (服务器冲突 ${Date.now()})${ext}`)
          tasks.push({ type: 'download', serverId: id, localPath: conflictPath })
        } else if (conflictStrategy === 'last-write-wins') {
          // 本地覆盖远端（让上行逻辑处理）
          warn(`Conflict on ${mirror.local_path}, last-write-wins: keeping local`)
        } else {
          // prefer-remote：下载覆盖本地
          tasks.push({ type: 'download', serverId: id, localPath: mirror.local_path, overwrite: true })
        }
        emit(EVENTS.CONFLICT, { localPath: mirror.local_path, serverNode: node })
      } else {
        // 仅远端改了 → 下载覆盖
        tasks.push({ type: 'download', serverId: id, localPath: mirror.local_path, overwrite: true })
      }
      upsertRemoteNode(node, mirror.local_path)
    } else {
      // 无变化，只刷新 local_path（可能 mirror 缺失）
      if (!mirror.local_path) {
        upsertRemoteNode(node, serverPathToLocal(syncRoot, node.parent_id, node.file_name))
      }
    }
  }

  // 3. 镜像有、远端无 → 远端已删 → 本地删除
  for (const mirror of mirrorNodes) {
    if (!remoteIds.has(mirror.id)) {
      if (mirror.local_path) {
        tasks.push({ type: 'delete_local', localPath: mirror.local_path, isFolder: mirror.is_folder })
      }
      deleteRemoteNode(mirror.id)
      deleteLocalState(mirror.local_path)
    }
  }

  return tasks
}

