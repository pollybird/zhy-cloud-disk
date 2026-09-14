/**
 * Web Worker：分块计算文件 MD5，避免阻塞主线程。
 * 使用 spark-md5 的 ArrayBuffer 增量模式。
 */
import SparkMD5 from 'spark-md5'

const CHUNK_SIZE = 2 * 1024 * 1024 // 2MB

self.onmessage = (e) => {
  const { file } = e.data
  const spark = new SparkMD5.ArrayBuffer()
  const total = file.size
  let cur = 0

  function readNext() {
    const end = Math.min(cur + CHUNK_SIZE, total)
    const reader = new FileReader()
    reader.onload = (ev) => {
      spark.append(ev.target.result)
      cur = end
      self.postMessage({ type: 'progress', progress: Math.round((cur / total) * 100) })
      if (cur < total) {
        readNext()
      } else {
        self.postMessage({ type: 'done', hash: spark.end() })
      }
    }
    reader.onerror = () => {
      self.postMessage({ type: 'error', msg: '文件读取失败' })
    }
    reader.readAsArrayBuffer(file.slice(cur, end))
  }

  if (total === 0) {
    self.postMessage({ type: 'done', hash: spark.end() })
  } else {
    readNext()
  }
}
