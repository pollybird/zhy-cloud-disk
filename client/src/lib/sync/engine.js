/**
 * 同步引擎编排器：协调 watcher + poller + queue + reconciler。
 * 生命周期：start / pause / resume / stop。
 * 首次运行时先全量下载，再进入常规循环。
 */
import path from 'path'
import fs from 'fs'
import { localWatcher } from './local-watcher.js'
import { remotePoller } from './remote-poller.js'
import { queue } from './queue.js'
import { reconcileRemote } from './reconciler.js'
import { computeMd5, getFileInfo } from './hasher.js'
import {
  initMirrorDb,
  isMirrorEmpty,
  isMirrorReady,
  clearAllMirror,
  upsertRemoteNode,
  upsertLocalState,
  getLocalState,
  getRemoteNode,
  deleteRemoteNode,
  deleteLocalState,
  closeMirrorDb,
  addSyncLog,
} from '../mirror/mirror-db.js'
import { serverPathToLocal, localPathToServerId, localParentToServerId } from '../paths.js'
import {
  downloadFile,
  uploadFile,
  checkDuplicate,
  createFolder,
  renameNode,
  moveNode,
  deleteNode,
} from '../api/file.js'
import { setCredentials } from '../api/client.js'
import { getSettings } from '../store/settings.js'
import { getAccessToken, getRefreshToken } from '../store/keystore.js'
import { emit, EVENTS } from '../events.js'
import { info, warn, error } from '../logger.js'

let state = 'idle' // idle | first-sync | syncing | paused | error
let syncRoot = ''
let conflictStrategy = 'keep-both'
let started = false

function setState(s) {
  state = s
  emit(EVENTS.STATE_CHANGE, s)
}

/**
 * 记录同步日志：写库 + 广播到渲染层。
 */
function logSync(action, fileName, localPath, status, message) {
  addSyncLog({ action, fileName, localPath, status, message })
  emit(EVENTS.LOG, { action, fileName, localPath, status, message })
}

export function getState() {
  return state
}

export async function start() {
  if (started) return
  started = true

  const settings = getSettings()
  syncRoot = settings.syncPath
  conflictStrategy = settings.conflictStrategy || 'keep-both'

  // 初始化镜像库
  initMirrorDb()

  // 注入 token
  const access = getAccessToken()
  const refresh = getRefreshToken()
  setCredentials(settings.serverUrl, access, refresh)

  // 确保同步根目录存在
  fs.mkdirSync(syncRoot, { recursive: true })

  // 注册任务处理器
  registerHandlers()

  setState('first-sync')
  info('Sync engine starting...')

  // 首次全量同步（镜像为空，或上次中断导致半写状态时重建）
  if (isMirrorEmpty()) {
    info('First sync: downloading all files...')
    await firstSync()
  } else if (!isMirrorReady()) {
    warn('Mirror is incomplete (interrupted last time), rebuilding...')
    clearAllMirror()
    await firstSync()
  }

  // 启动 watcher 和 poller
  localWatcher.start(syncRoot)
  remotePoller.setInterval(settings.pollInterval || 60)
  remotePoller.onSnapshot = handleRemoteSnapshot
  remotePoller.start()

  setState('idle')
  info('Sync engine started')
}

export function pause() {
  setState('paused')
  localWatcher.stop()
  remotePoller.stop()
  info('Sync engine paused')
}

export function resume() {
  if (!started) {
    return start()
  }
  setState('idle')
  localWatcher.start(syncRoot)
  remotePoller.start()
  info('Sync engine resumed')
}

export function stop() {
  localWatcher.stop()
  remotePoller.stop()
  queue.clear()
  closeMirrorDb()
  started = false
  setState('idle')
  info('Sync engine stopped')
}

/**
 * 首次全量同步：拉取远端全树，建目录、下载所有文件。
 */
async function firstSync() {
  const snapshot = await remotePoller.fetchFullTree()

  // 按目录拓扑序建目录（先 parent_id=null 的文件夹，再深层）
  const folders = []
  const files = []
  for (const node of snapshot.values()) {
    if (node.is_folder) folders.push(node)
    else files.push(node)
  }

  // 按层级排序（parent_id 小的先建）
  folders.sort((a, b) => {
    if (a.parent_id == null) return -1
    if (b.parent_id == null) return 1
    return a.parent_id - b.parent_id
  })

  // 建目录
  for (const folder of folders) {
    const localPath = serverPathToLocal(syncRoot, folder.parent_id, folder.file_name)
    try {
      await fs.promises.mkdir(localPath, { recursive: true })
      upsertRemoteNode(folder, localPath)
    } catch (e) {
      error(`mkdir failed: ${localPath}: ${e.message}`)
    }
  }

  // 下载文件
  let count = 0
  for (const file of files) {
    const localPath = serverPathToLocal(syncRoot, file.parent_id, file.file_name)
    try {
      emit(EVENTS.PROGRESS, { current: ++count, total: files.length, fileName: file.file_name })
      await downloadFile(file.id, localPath)
      upsertRemoteNode(file, localPath)
      const fileInfo = await getFileInfo(localPath)
      upsertLocalState({
        local_path: localPath,
        server_id: file.id,
        local_mtime: fileInfo.mtime,
        local_size: fileInfo.size,
        local_md5: fileInfo.md5,
        state: 'synced',
      })
      logSync('download', file.file_name, localPath, 'success')
    } catch (e) {
      error(`download failed: ${file.file_name}: ${e.message}`)
      logSync('download', file.file_name, localPath, 'failed', e.message)
    }
  }

  emit(EVENTS.PROGRESS, { current: count, total: files.length, fileName: '' })
  info(`First sync complete: ${count} files downloaded`)
}

/**
 * 远端轮询回调：reconcile 后把任务灌入队列。
 */
async function handleRemoteSnapshot(snapshot) {
  if (state === 'paused') return
  setState('syncing')
  const tasks = reconcileRemote(snapshot, syncRoot, conflictStrategy)
  if (tasks.length > 0) {
    queue.addAll(tasks)
  }
  // 队列执行完后会自然回到 idle
  // 简单起见用定时检查
  const checkInterval = setInterval(() => {
    if (queue.size() === 0) {
      clearInterval(checkInterval)
      setState('idle')
    }
  }, 1000)
}

// ---- 任务处理器注册 ----

function registerHandlers() {
  // 下载
  queue.register('download', async (task) => {
    info(`Downloading: ${task.localPath}`)
    const node = await getNodeFromServer(task.serverId)
    await downloadFile(task.serverId, task.localPath, {
      expectedSize: node?.file_size ?? null,
      expectedHash: node?.file_hash ?? null,
    })
    if (node) upsertRemoteNode(node, task.localPath)
    const fileInfo = await getFileInfo(task.localPath)
    upsertLocalState({
      local_path: task.localPath,
      server_id: task.serverId,
      local_mtime: fileInfo.mtime,
      local_size: fileInfo.size,
      local_md5: fileInfo.md5,
      state: 'synced',
    })
    logSync('download', path.basename(task.localPath), task.localPath, 'success')
  })

  // 本地建目录
  queue.register('mkdir_local', async (task) => {
    await fs.promises.mkdir(task.localPath, { recursive: true })
  })

  // 本地移动/改名
  queue.register('move_local', async (task) => {
    try {
      await fs.promises.rename(task.oldPath, task.newPath)
      const state = getLocalState(task.oldPath)
      if (state) {
        deleteLocalState(task.oldPath)
        upsertLocalState({ ...state, local_path: task.newPath })
      }
    } catch (e) {
      warn(`move_local failed: ${e.message}`)
    }
  })

  // 本地删除
  queue.register('delete_local', async (task) => {
    try {
      if (task.isFolder) {
        await fs.promises.rm(task.localPath, { recursive: true, force: true })
      } else {
        await fs.promises.unlink(task.localPath)
      }
    } catch (e) {
      if (e.code !== 'ENOENT') warn(`delete_local failed: ${e.message}`)
    }
    deleteLocalState(task.localPath)
  })

  // 上传到远端
  queue.register('upload', async (task) => {
    info(`Uploading: ${task.localPath}`)
    const md5 = await computeMd5(task.localPath)
    const fileName = path.basename(task.localPath)
    const result = await checkDuplicate(task.serverParentId, fileName, md5)

    if (result.action === 'skip') {
      info(`Skipped (same content): ${fileName}`)
      logSync('upload', fileName, task.localPath, 'skipped', '云端内容一致，已跳过')
      return
    }

    if (result.action === 'conflict') {
      // 用覆盖模式
      const node = await uploadFile(task.localPath, task.serverParentId, md5, 'overwrite', result.existing?.id)
      upsertRemoteNode(node, task.localPath)
      const fi = await getFileInfo(task.localPath)
      upsertLocalState({
        local_path: task.localPath,
        server_id: node.id,
        local_mtime: fi.mtime,
        local_size: fi.size,
        local_md5: md5,
        state: 'synced',
      })
      logSync('upload', fileName, task.localPath, 'success', '已覆盖云端同名文件')
      return
    }

    // action === 'upload'：1.2.0 起先秒传、大文件分片续传
    const { node: uploadedNode, instant } = await uploadLocal(task.localPath, {
      parentId: task.serverParentId,
      fileHash: md5,
    })
    if (!uploadedNode?.id) {
      throw new Error('上传响应异常')
    }
    upsertRemoteNode(uploadedNode, task.localPath)
    const fi = await getFileInfo(task.localPath)
    upsertLocalState({
      local_path: task.localPath,
      server_id: uploadedNode.id,
      local_mtime: fi.mtime,
      local_size: fi.size,
      local_md5: md5,
      state: 'synced',
    })
    logSync(
      'upload',
      fileName,
      task.localPath,
      'success',
      instant ? '秒传完成' : undefined,
    )
  })

  // 远端删除
  queue.register('delete_remote', async (task) => {
    info(`Deleting remote: ${task.serverId}`)
    await deleteNode(task.serverId)
    deleteRemoteNode(task.serverId)
    deleteLocalState(task.localPath)
    logSync(
      'delete',
      task.localPath ? path.basename(task.localPath) : null,
      task.localPath,
      'success',
      '已删除'
    )
  })

  // 远端改名
  queue.register('rename_remote', async (task) => {
    info(`Renaming remote: ${task.serverId} -> ${task.newName}`)
    const node = await renameNode(task.serverId, task.newName)
    const mirror = getRemoteNode(task.serverId)
    if (mirror) upsertRemoteNode(node, mirror.local_path)
    logSync('rename', task.newName, mirror?.local_path, 'success')
  })

  // 远端移动
  queue.register('move_remote', async (task) => {
    info(`Moving remote: ${task.serverId} -> parent ${task.targetParentId}`)
    const node = await moveNode(task.serverId, task.targetParentId)
    const mirror = getRemoteNode(task.serverId)
    if (mirror) {
      const newPath = serverPathToLocal(syncRoot, node.parent_id, node.file_name)
      upsertRemoteNode(node, newPath)
      logSync('move', node.file_name, newPath, 'success')
    }
  })

  // ---- 注册本地 watcher 回调 → 生成上行任务 ----

  localWatcher.on('onAdd', (localPath, serverParentId) => {
    setState('syncing')
    queue.add({ type: 'upload', localPath, serverParentId })
  })

  localWatcher.on('onChange', async (localPath, _fileInfo, localState) => {
    setState('syncing')
    if (!localState || !localState.server_id) {
      // 无 server_id，当新增处理
      const serverParentId = localParentToServerId(syncRoot, path.dirname(localPath))
      queue.add({ type: 'upload', localPath, serverParentId })
      return
    }
    // 覆盖上传
    queue.add({
      type: 'upload',
      localPath,
      serverParentId: localParentToServerId(syncRoot, path.dirname(localPath)),
    })
  })

  localWatcher.on('onDelete', (localPath) => {
    setState('syncing')
    const serverId = localPathToServerId(localPath)
    if (serverId) {
      queue.add({ type: 'delete_remote', serverId, localPath })
    }
  })

  localWatcher.on('onAddDir', (localPath, serverParentId) => {
    setState('syncing')
    queue.add({ type: 'create_folder_remote', localPath, serverParentId })
  })

  localWatcher.on('onDeleteDir', (localPath) => {
    setState('syncing')
    const serverId = localPathToServerId(localPath)
    if (serverId) {
      queue.add({ type: 'delete_remote', serverId, localPath })
    }
  })

  localWatcher.on('onRename', (oldPath, newPath, serverId) => {
    setState('syncing')
    if (serverId) {
      queue.add({ type: 'rename_remote', serverId, newName: path.basename(newPath) })
      // 更新本地状态
      const state = getLocalState(oldPath)
      if (state) {
        deleteLocalState(oldPath)
        upsertLocalState({ ...state, local_path: newPath })
      }
    }
  })

  localWatcher.on('onMove', (oldPath, newPath, serverId, targetParentId) => {
    setState('syncing')
    if (serverId) {
      queue.add({ type: 'move_remote', serverId, targetParentId })
      const state = getLocalState(oldPath)
      if (state) {
        deleteLocalState(oldPath)
        upsertLocalState({ ...state, local_path: newPath })
      }
    }
  })

  // 建文件夹远端
  queue.register('create_folder_remote', async (task) => {
    info(`Creating remote folder: ${task.localPath}`)
    const folderName = path.basename(task.localPath)
    const node = await createFolder(task.serverParentId, folderName)
    upsertRemoteNode(node, task.localPath)
    logSync('mkdir', folderName, task.localPath, 'success', '文件夹已创建')
  })
}

async function getNodeFromServer(id) {
  // 从最近一次 poll 的 snapshot 获取，或直接查 mirror
  return getRemoteNode(id)
}
