/**
 * 1.2.0 HTTP Range 断点续传下载（Electron 主进程）。
 *
 * - 落盘 savePath + '.zhy.part'，完成后原子 rename
 * - '.zhy.meta' 记录 fileId/期望大小，防止不同文件复用同一临时文件造成脏续传
 * - 服务端支持 Range 时从断点追加（206），不支持/被忽略则整体重下（200）
 * - 完成后校验大小与（可选）MD5
 */
import fs from 'fs'
import fsp from 'fs/promises'
import path from 'path'
import { pipeline } from 'stream/promises'
import http from '../api/client.js'
import { computeMd5 } from './hasher.js'

/**
 * @param {number} fileId 服务端节点 id
 * @param {string} savePath 最终保存路径
 * @param {object} [opts]
 * @param {number|null} [opts.expectedSize] 期望文件大小（用于断点合法性与完成校验）
 * @param {string|null} [opts.expectedHash] 期望 MD5（传则完成后校验）
 * @param {string} [opts.key] 临时文件身份标识（默认 fileId）
 * @param {(received:number,total:number)=>void} [opts.onProgress] received 含已存在部分
 */
export async function downloadResumable(fileId, savePath, opts = {}) {
  const {
    expectedSize = null,
    expectedHash = null,
    key = String(fileId),
    onProgress = null,
  } = opts

  const tmpPath = `${savePath}.zhy.part`
  const metaPath = `${tmpPath}.meta`
  const meta = `${key}:${expectedSize ?? ''}`

  let start = 0
  try {
    const partStat = await fsp.stat(tmpPath)
    const savedMeta = await fsp.readFile(metaPath, 'utf8')
    // 同一文件、未超额才续传；否则从头开始
    if (
      savedMeta === meta
      && (!expectedSize || (partStat.size > 0 && partStat.size < expectedSize))
    ) {
      start = partStat.size
    }
  } catch {
    start = 0
  }

  // meta 先落盘，中断后才能安全续传
  await fsp.mkdir(path.dirname(savePath), { recursive: true })
  await fsp.writeFile(metaPath, meta)

  const res = await http.get('/api/file/download', {
    params: { id: fileId },
    responseType: 'stream',
    headers: start > 0 ? { Range: `bytes=${start}-` } : {},
    timeout: 0,
  })

  const status = res.status
  if (status !== 200 && status !== 206) {
    throw new Error(`下载失败：HTTP ${status}`)
  }
  if (status === 200) start = 0

  // 总大小：206 优先解析 Content-Range，其次 Content-Length + 已有字节
  let total = expectedSize || 0
  const contentRange = res.headers?.['content-range']
  const contentLength = Number(res.headers?.['content-length'] || 0)
  if (status === 206 && contentRange) {
    const m = /\/(\d+)$/.exec(contentRange)
    if (m) total = Number(m[1])
  } else if (!total && contentLength > 0) {
    total = contentLength
  }

  let received = start
  res.data.on('data', (chunk) => {
    received += chunk.length
    if (onProgress && total > 0) onProgress(received, total)
  })

  const writer = fs.createWriteStream(tmpPath, { flags: status === 206 ? 'a' : 'w' })
  await pipeline(res.data, writer)

  const finalStat = await fsp.stat(tmpPath)
  if (expectedSize && finalStat.size !== expectedSize) {
    throw new Error(`下载大小不符：期望 ${expectedSize}，实际 ${finalStat.size}`)
  }
  if (expectedHash) {
    const actual = await computeMd5(tmpPath)
    if (actual !== expectedHash) {
      throw new Error('下载文件指纹校验失败')
    }
  }

  await fsp.rename(tmpPath, savePath)
  await fsp.unlink(metaPath).catch(() => {})
  return savePath
}
