/**
 * 文件操作接口，严格按后端实际签名封装。
 * 后端路由：backend/app/api/file.py
 */
import http from './client.js'
import fs from 'fs'
import path from 'path'
import { pipeline } from 'stream/promises'

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
