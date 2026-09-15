/**
 * 流式 MD5 计算：crypto.createHash 分块读取，避免大文件内存溢出。
 */
import crypto from 'crypto'
import fs from 'fs'

const CHUNK_SIZE = 2 * 1024 * 1024 // 2MB

export async function computeMd5(filePath) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash('md5')
    const stream = fs.createReadStream(filePath, { highWaterMark: CHUNK_SIZE })
    stream.on('data', (chunk) => hash.update(chunk))
    stream.on('end', () => resolve(hash.digest('hex')))
    stream.on('error', reject)
  })
}

export async function getFileInfo(filePath) {
  const stat = await fs.promises.stat(filePath)
  const md5 = await computeMd5(filePath)
  return {
    size: stat.size,
    mtime: Math.floor(stat.mtimeMs / 1000),
    md5,
  }
}
