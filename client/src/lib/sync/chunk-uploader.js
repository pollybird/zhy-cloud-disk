/**
 * 1.2.0 大文件分片上传（Electron 主进程）。
 *
 * - fs 随机读切片（不整体载入内存），crypto 计算单片 MD5
 * - 并发 3、单片失败重试 3 次
 * - init 自动恢复同用户同内容未完成会话（断点续传）
 * - 正常新文件先尝试跨用户秒传，命中零流量
 *
 * 依赖通过默认参数注入，便于单测。
 */
import fs from 'fs'
import fsp from 'fs/promises'
import path from 'path'
import crypto from 'crypto'
import {
  chunkAbort,
  chunkComplete,
  chunkInit as apiChunkInit,
  instantUpload as apiInstant,
  uploadChunkPart,
  uploadFile,
} from '../api/file.js'
import { uploadDeptFile } from '../api/department.js'
import { computeMd5 } from './hasher.js'

export const CHUNK_SIZE = 5 * 1024 * 1024
export const CHUNK_THRESHOLD = 20 * 1024 * 1024
export const CHUNK_CONCURRENCY = 3
export const CHUNK_RETRY = 3

/** 从文件指定位置读取一片，返回 { buffer, hash }。 */
export async function readChunk(filePath, index, chunkSize, fileSize) {
  const start = index * chunkSize
  const length = Math.min(chunkSize, fileSize - start)
  const buffer = Buffer.allocUnsafe(length)
  const fh = await fsp.open(filePath, 'r')
  try {
    const { bytesRead } = await fh.read(buffer, 0, length, start)
    if (bytesRead !== length) throw new Error(`读取分片 ${index} 不完整`)
  } finally {
    await fh.close()
  }
  return { buffer, hash: crypto.createHash('md5').update(buffer).digest('hex') }
}

/** 纯函数：待传分片序号。 */
export function pendingIndexes(received, total) {
  const done = new Set(received || [])
  const out = []
  for (let i = 0; i < total; i += 1) {
    if (!done.has(i)) out.push(i)
  }
  return out
}

function isAbortError(err, signal) {
  return Boolean(
    signal?.aborted
    || err?.code === 'ERR_CANCELED'
    || err?.name === 'CanceledError'
    || err?.canceled,
  )
}

/**
 * 分片上传主流程。
 * @param {object} opts
 * @returns {Promise<{node:object, instant:boolean}>}
 */
export async function uploadInChunks({
  filePath,
  fileSize,
  fileHash,
  parentId = null,
  departmentId = null,
  chunkSize = CHUNK_SIZE,
  onProgress = null,
  signal = null,
  api = {
    chunkInit: apiChunkInit,
    uploadPart: uploadChunkPart,
    complete: chunkComplete,
    abort: chunkAbort,
    readChunk: (idx) => readChunk(filePath, idx, chunkSize, fileSize),
  },
}) {
  const init = await api.chunkInit({
    file_name: path.basename(filePath),
    file_size: fileSize,
    file_hash: fileHash,
    chunk_size: chunkSize,
    parent_id: parentId ?? null,
    department_id: departmentId ?? null,
  })

  // init 直接命中：走秒传接口取节点
  if (init.instant) {
    const r = await apiInstant({
      file_name: path.basename(filePath),
      file_size: fileSize,
      file_hash: fileHash,
      parent_id: parentId ?? null,
      department_id: departmentId ?? null,
    })
    return { node: r.node, instant: true }
  }

  const uploadId = init.upload_id
  const total = init.total_chunks
  const received = new Set(init.received || [])

  const emit = (extraBytes = 0) => {
    if (!onProgress) return
    const doneBytes = received.size * chunkSize + extraBytes
    const ratio = Math.min(doneBytes, fileSize) / fileSize
    onProgress(Math.min(99, Math.round(ratio * 100)))
  }
  emit(0)

  const pending = pendingIndexes([...received], total)

  const uploadOne = async (index) => {
    let lastErr = null
    for (let attempt = 0; attempt < CHUNK_RETRY; attempt += 1) {
      try {
        // 取消后不再发起请求
        if (signal?.aborted) {
          const err = new Error('aborted')
          err.canceled = true
          throw err
        }
        // eslint-disable-next-line no-await-in-loop
        const { buffer, hash } = await api.readChunk(index)
        // eslint-disable-next-line no-await-in-loop
        await api.uploadPart(uploadId, index, buffer, hash, signal)
        received.add(index)
        emit(0)
        return
      } catch (err) {
        lastErr = err
        if (isAbortError(err, signal)) throw err
      }
    }
    throw lastErr || new Error(`分片 ${index} 上传失败`)
  }

  let cursor = 0
  const workers = Array.from(
    { length: Math.min(CHUNK_CONCURRENCY, pending.length) },
    async () => {
      while (cursor < pending.length) {
        const index = pending[cursor]
        cursor += 1
        // eslint-disable-next-line no-await-in-loop
        await uploadOne(index)
      }
    },
  )
  await Promise.all(workers)

  const done = await api.complete(uploadId)
  onProgress?.(100)
  return { node: done.node, instant: false }
}

/**
 * 统一上传入口（部门/个人通用）：
 * - overwrite 模式：沿用整文件上传（服务端覆盖语义）
 * - normal：先秒传 → 大文件分片 → 小文件整文件
 *
 * @param {string} filePath 本地绝对路径
 * @param {object} payload
 * @returns {Promise<{node:object, instant:boolean, skipped?:boolean}>}
 */
export async function uploadLocal(filePath, payload = {}) {
  const {
    parentId = null,
    departmentId = null,
    fileHash = null,
    mode = 'normal',
    overwriteId = null,
    onProgress = null,
    signal = null,
    chunks = uploadInChunks,
  } = payload

  const fileName = path.basename(filePath)

  // 覆盖上传保持整文件通道
  if (mode === 'overwrite') {
    const res = departmentId != null
      ? await uploadDeptFile(filePath, {
        departmentId, parentId, fileHash, mode, overwriteId, onProgress,
      })
      : await uploadFile(filePath, parentId ?? null, fileHash, 'overwrite', overwriteId)
    return { node: res?.success?.[0] || res, instant: false }
  }

  const st = await fsp.stat(filePath)
  const hash = fileHash || (await computeMd5(filePath))

  // 1) 跨用户秒传（任意大小，零流量）
  try {
    const r = await apiInstant({
      parent_id: parentId ?? null,
      department_id: departmentId ?? null,
      file_name: fileName,
      file_size: st.size,
      file_hash: hash,
    })
    if (r.instant) {
      onProgress?.(100)
      return { node: r.node, instant: true, skipped: Boolean(r.skipped) }
    }
  } catch (err) {
    if (isAbortError(err, signal)) throw err
    // 秒传检测失败不影响正常上传
  }

  // 2) 大文件分片
  if (st.size > CHUNK_THRESHOLD) {
    return chunks({
      filePath,
      fileSize: st.size,
      fileHash: hash,
      parentId: parentId ?? null,
      departmentId: departmentId ?? null,
      onProgress,
      signal,
    })
  }

  // 3) 小文件整文件
  const res = departmentId != null
    ? await uploadDeptFile(filePath, { departmentId, parentId, fileHash: hash, onProgress })
    : await uploadFile(filePath, parentId ?? null, hash, 'normal')
  return { node: res?.success?.[0] || res, instant: false }
}

/** 取消后通知服务端清理会话（尽力而为）。 */
export async function abortChunked(uploadId, api = { abort: chunkAbort }) {
  if (!uploadId) return
  try {
    await api.abort(uploadId)
  } catch {
    /* GC 兜底 */
  }
}
