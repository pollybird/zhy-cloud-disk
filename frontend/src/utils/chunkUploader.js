/**
 * 1.2.0 大文件分片上传编排器（Web 端）。
 *
 * 流程：chunk/init（可能直接 instant）→ 按 received 续传缺失分片（并发 3、单片重试 3 次）
 *      → chunk/complete；取消时 chunk/abort。
 * 小文件（≤ CHUNK_THRESHOLD）由调用方继续走整文件 /api/file/upload。
 */
import {
  chunkAbort,
  chunkComplete,
  chunkInit,
  instantUpload,
  uploadChunk,
} from '../api/file'

export const CHUNK_SIZE = 5 * 1024 * 1024
export const CHUNK_THRESHOLD = 20 * 1024 * 1024
export const CHUNK_CONCURRENCY = 3
export const CHUNK_RETRY = 3

export function shouldUseChunk(file) {
  return Boolean(file) && typeof file.size === 'number' && file.size > CHUNK_THRESHOLD
}

/** 计算总分片数。 */
export function totalChunks(fileSize, chunkSize = CHUNK_SIZE) {
  return Math.ceil(fileSize / chunkSize)
}

/** 断点续传：根据服务端已收序号求待传序号。 */
export function pendingIndexes(received, total) {
  const done = new Set(received || [])
  const result = []
  for (let i = 0; i < total; i += 1) {
    if (!done.has(i)) result.push(i)
  }
  return result
}

/**
 * 已完成字节进度（0~99，complete 前不到 100）。
 * @param {number[]} received 已确认分片序号
 * @param {number} total 总分片数
 * @param {number} fileSize 文件总字节
 * @param {number} currentBytes 当前在传分片的已传字节
 */
export function progressFromReceived(received, total, fileSize, currentBytes = 0) {
  const doneBytes = (received || []).length * CHUNK_SIZE
  const ratio = Math.min(doneBytes + currentBytes, fileSize) / fileSize
  return Math.min(99, Math.round(ratio * 100))
}

function isCanceled(err) {
  return err?.code === 'ERR_CANCELED' || err?.name === 'CanceledError' || err?.canceled
}

/**
 * 先尝试秒传（零流量）。
 * @returns {Promise<{instant:boolean, skipped?:boolean, node?:object}>}
 */
export async function tryInstant({ file, hash, parentId, departmentId }) {
  const res = await instantUpload({
    file_name: file.name,
    file_size: file.size,
    file_hash: hash,
    parent_id: parentId || null,
    department_id: departmentId || null,
  })
  return res.data
}

/**
 * 分片上传一个文件。
 * @param {object} opts
 * @param {File} opts.file
 * @param {string} opts.hash 整文件 MD5
 * @param {number|null} opts.parentId
 * @param {number|null} opts.departmentId
 * @param {(p:number)=>void} [opts.onProgress]
 * @param {AbortSignal} [opts.signal]
 * @returns {Promise<{node:object}>}
 */
export async function uploadInChunks({
  file, hash, parentId = null, departmentId = null,
  onProgress = null, signal = null,
}) {
  const initRes = await chunkInit({
    file_name: file.name,
    file_size: file.size,
    file_hash: hash,
    chunk_size: CHUNK_SIZE,
    parent_id: parentId || null,
    department_id: departmentId || null,
  })
  const init = initRes.data
  if (init.instant) {
    const r = await tryInstant({ file, hash, parentId, departmentId })
    return { node: r.node, instant: true }
  }

  const uploadId = init.upload_id
  const total = init.total_chunks
  const received = new Set(init.received || [])
  const emit = (currentBytes = 0) => {
    if (onProgress) {
      onProgress(progressFromReceived([...received], total, file.size, currentBytes))
    }
  }
  emit(0)

  const pending = pendingIndexes([...received], total)

  const uploadOne = async (index) => {
    const start = index * CHUNK_SIZE
    const blob = file.slice(start, Math.min(start + CHUNK_SIZE, file.size))
    const form = new FormData()
    form.append('upload_id', uploadId)
    form.append('index', String(index))
    form.append('chunk', blob, `${index}.part`)

    let lastErr = null
    for (let attempt = 0; attempt < CHUNK_RETRY; attempt += 1) {
      try {
        await uploadChunk(form, (e) => emit(index * CHUNK_SIZE + e.loaded), signal)
        received.add(index)
        emit(0)
        return
      } catch (err) {
        lastErr = err
        if (isCanceled(err) || signal?.aborted) throw err
      }
    }
    throw lastErr || new Error(`分片 ${index} 上传失败`)
  }

  // 简单并发池
  let cursor = 0
  const workers = Array.from({ length: Math.min(CHUNK_CONCURRENCY, pending.length) }, async () => {
    while (cursor < pending.length) {
      const index = pending[cursor]
      cursor += 1
      await uploadOne(index)
    }
  })
  await Promise.all(workers)

  const doneRes = await chunkComplete(uploadId)
  return { node: doneRes.data.node, instant: false }
}

/** 取消上传：通知服务端清理暂存（尽力而为）。 */
export async function abortChunked(uploadIdOrNull) {
  if (!uploadIdOrNull) return
  try {
    await chunkAbort(uploadIdOrNull)
  } catch {
    /* 忽略清理失败，GC 兜底 */
  }
}
