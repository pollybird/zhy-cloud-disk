/**
 * 文件操作接口，严格按后端实际签名封装。
 * 后端路由：backend/app/api/file.py
 */
import http from './client.js'
import fs from 'fs'
import path from 'path'
import { pipeline } from 'stream/promises'
import { downloadResumable } from '../sync/range-downloader.js'

/**
 * 列出文件/文件夹（分页）。
 * GET /api/file/list?parent_id=&page=&size=
 */
export async function listFiles(parentId = null, page = 1, size = 200) {
  const res = await http.get('/api/file/list', {
    params: { parent_id: parentId ?? '', page, size },
  })
  return res.data
}

/**
 * 列出子文件夹。
 * GET /api/file/folders?parent_id=
 */
export async function listFolders(parentId = null) {
  const res = await http.get('/api/file/folders', {
    params: { parent_id: parentId ?? '' },
  })
  return res.data.items
}

/**
 * 下载文件到指定本地路径（流式写入）。
 * GET /api/file/download?id=
 */
export async function downloadFile(fileId, savePath) {
  const tmpPath = savePath + '.zhy.part'
  const res = await http.get('/api/file/download', {
    params: { id: fileId },
    responseType: 'stream',
  })
  const writer = fs.createWriteStream(tmpPath)
  await pipeline(res.data, writer)
  await fs.promises.rename(tmpPath, savePath)
  return savePath
}

/**
 * 上传文件（multipart form）。
 * POST /api/file/upload
 * 字段：files, parent_id, file_hash, mode, overwrite_id
 */
export async function uploadFile(filePath, parentId = null, fileHash = null, mode = 'normal', overwriteId = null) {
  const fileName = path.basename(filePath)
  const fd = new FormData()
  fd.append('files', new Blob([await fs.promises.readFile(filePath)]), fileName)
  if (parentId) fd.append('parent_id', String(parentId))
  if (fileHash) fd.append('file_hash', fileHash)
  if (mode !== 'normal') fd.append('mode', mode)
  if (overwriteId) fd.append('overwrite_id', String(overwriteId))

  const res = await http.post('/api/file/upload', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
    maxContentLength: Infinity,
    maxBodyLength: Infinity,
  })
  return res.data
}

/**
 * 上传前查重。
 * POST /api/file/check-duplicate
 * body: { parent_id, file_name, file_hash }
 */
export async function checkDuplicate(parentId, fileName, fileHash = null) {
  const res = await http.post('/api/file/check-duplicate', {
    parent_id: parentId ?? null,
    file_name: fileName,
    file_hash: fileHash,
  })
  return res.data
}

/**
 * 1.2.0 跨用户秒传：凭 MD5+大小零流量建引用。
 * POST /api/file/instant
 * @returns {Promise<{instant:boolean, skipped?:boolean, node?:object}>}
 */
export async function instantUpload(payload) {
  const res = await http.post('/api/file/instant', payload)
  return res.data
}

/**
 * 1.2.0 分片上传：初始化/恢复会话。
 * POST /api/file/chunk/init
 * @returns {Promise<{instant:boolean, upload_id?:string, total_chunks?:number, received?:number[]}>}
 */
export async function chunkInit(payload) {
  const res = await http.post('/api/file/chunk/init', payload)
  return res.data
}

/**
 * 上传单个分片（Buffer，由主进程 fs 切片产生）。
 * POST /api/file/chunk/upload
 */
export async function uploadChunkPart(uploadId, index, buffer, chunkHash = null, signal = null) {
  const fd = new FormData()
  fd.append('upload_id', uploadId)
  fd.append('index', String(index))
  fd.append('chunk', new Blob([buffer]), `${index}.part`)
  if (chunkHash) fd.append('chunk_hash', chunkHash)
  const res = await http.post('/api/file/chunk/upload', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
    maxContentLength: Infinity,
    maxBodyLength: Infinity,
    timeout: 0,
    signal: signal || undefined,
  })
  return res.data
}

/** 合并分片完成上传。POST /api/file/chunk/complete */
export async function chunkComplete(uploadId) {
  const res = await http.post('/api/file/chunk/complete', { upload_id: uploadId })
  return res.data
}

/** 取消分片会话（尽力而为，服务端 GC 兜底）。POST /api/file/chunk/abort */
export async function chunkAbort(uploadId) {
  const res = await http.post('/api/file/chunk/abort', { upload_id: uploadId })
  return res.data
}

/** 查询会话已收分片（断点恢复）。GET /api/file/chunk/status */
export async function chunkStatus(uploadId) {
  const res = await http.get('/api/file/chunk/status', { params: { upload_id: uploadId } })
  return res.data
}

/**
 * 创建文件夹。
 * POST /api/folder/create
 * body: { parent_id, file_name }
 */
export async function createFolder(parentId = null, fileName) {
  const res = await http.post('/api/folder/create', {
    parent_id: parentId ?? null,
    file_name: fileName,
  })
  return res.data
}

/**
 * 重命名。
 * PUT /api/file/rename
 * body: { id, file_name }
 */
export async function renameNode(id, fileName) {
  const res = await http.put('/api/file/rename', { id, file_name: fileName })
  return res.data
}

/**
 * 移动。
 * PUT /api/file/move
 * body: { id, target_parent_id }
 */
export async function moveNode(id, targetParentId) {
  const res = await http.put('/api/file/move', {
    id,
    target_parent_id: targetParentId ?? null,
  })
  return res.data
}

/**
 * 删除（单 id）。
 * DELETE /api/file/delete
 * body: { id }
 */
export async function deleteNode(id) {
  const res = await http.delete('/api/file/delete', { data: { id } })
  return res.data
}

/**
 * 1.2.0 部门文件排他编辑锁。
 * 打开编辑前 acquire（幂等续约），编辑期间 heartbeat（约 30s），
 * 保存/关闭后 release；他人持锁时 acquire 抛 code=3501，err.data.user_name 为持有者。
 */
export async function lockAcquire(id) {
  const res = await http.post('/api/file/lock/acquire', { id })
  return res.data
}

export async function lockHeartbeat(id) {
  const res = await http.post('/api/file/lock/heartbeat', { id })
  return res.data
}

export async function lockRelease(id, force = false) {
  const res = await http.post('/api/file/lock/release', { id, force })
  return res.data
}

export async function lockStatus(id) {
  const res = await http.get('/api/file/lock/status', { params: { id } })
  return res.data
}

/**
 * 1.3.0 回收站：列表。
 * GET /api/file/trash?scope=personal|department&department_id=
 */
export async function listTrash({ scope = 'personal', departmentId = null } = {}) {
  const res = await http.get('/api/file/trash', {
    params: {
      scope,
      ...(scope === 'department' ? { department_id: departmentId } : {}),
    },
  })
  return res.data
}

/** 还原回收站单项。POST /api/file/trash/restore body: { id } */
export async function restoreTrashItem(id) {
  const res = await http.post('/api/file/trash/restore', { id })
  return res.data
}

/** 彻底删除回收站单项（含历史版本与存储实体）。DELETE /api/file/trash/item body: { id } */
export async function purgeTrashItem(id) {
  const res = await http.delete('/api/file/trash/item', { data: { id } })
  return res.data
}

/** 清空回收站。DELETE /api/file/trash?scope=&department_id= */
export async function emptyTrash({ scope = 'personal', departmentId = null } = {}) {
  const res = await http.delete('/api/file/trash', {
    params: {
      scope,
      ...(scope === 'department' ? { department_id: departmentId } : {}),
    },
  })
  return res.data
}

/**
 * 1.3.0 历史版本：列表（含当前版本信息）。
 * GET /api/file/versions/<node_id>
 * @returns {Promise<{current:{file_hash,file_size,upload_time}, items:Array}>}
 */
export async function listVersions(nodeId) {
  const res = await http.get(`/api/file/versions/${nodeId}`)
  return res.data
}

/** 下载指定历史版本到本地路径（流式写入）。GET /api/file/version/download?version_id= */
export async function downloadVersion(versionId, savePath) {
  const tmpPath = savePath + '.zhy.part'
  const res = await http.get('/api/file/version/download', {
    params: { version_id: versionId },
    responseType: 'stream',
  })
  const writer = fs.createWriteStream(tmpPath)
  await pipeline(res.data, writer)
  await fs.promises.rename(tmpPath, savePath)
  return savePath
}

/** 恢复指定历史版本（当前内容转为新版本，可来回切换）。POST /api/file/version/restore body: { version_id } */
export async function restoreVersion(versionId) {
  const res = await http.post('/api/file/version/restore', { version_id: versionId })
  return res.data
}
