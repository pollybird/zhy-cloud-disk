/**
 * 远端轮询器：定时全树拉取，构建 remoteSnapshot: Map<id, node>。
 * 从根 parent_id=null 开始 BFS，分页拉取每层子节点。
 */
import { listFiles } from '../api/file.js'
import { info, warn } from '../logger.js'

const MAX_CONCURRENT = 4

class RemotePoller {
  constructor() {
    this.timer = null
    this.interval = 60 // 秒
    this.running = false
    this.onSnapshot = null
    this.errorCount = 0
  }

  setInterval(seconds) {
    this.interval = seconds
    if (this.timer) {
      this.stop()
      this.start()
    }
  }

  start() {
    if (this.timer) return
    // 立即执行一次
    this._poll()
    this.timer = setInterval(() => this._poll(), this.interval * 1000)
    info(`Remote poller started, interval=${this.interval}s`)
  }

  stop() {
    if (this.timer) {
      clearInterval(this.timer)
      this.timer = null
    }
  }

  async _poll() {
    if (this.running) return
    this.running = true
    try {
      const snapshot = await this.fetchFullTree()
      this.errorCount = 0
      if (this.onSnapshot) await this.onSnapshot(snapshot)
    } catch (e) {
      this.errorCount++
      const delay = Math.min(60 * Math.pow(2, Math.min(this.errorCount - 1, 4)), 600)
      warn(`Poll failed (${this.errorCount}x): ${e.message}, retrying in ${delay}s`)
      // 重新调度下一次
      if (this.timer) {
        clearInterval(this.timer)
        this.timer = setInterval(() => this._poll(), delay * 1000)
      }
    } finally {
      this.running = false
    }
  }

  /**
   * 全树拉取，返回 Map<id, node>。
   * BFS：从根开始，逐层拉取每个 parent_id 下的所有节点。
   */
  async fetchFullTree() {
    const snapshot = new Map()
    const queue = [null] // 从根 parent_id=null 开始
    const visited = new Set()

    while (queue.length > 0) {
      // 批量取，限制并发
      const batch = queue.splice(0, MAX_CONCURRENT)
      const results = await Promise.all(batch.map((pid) => this._fetchAllInParent(pid)))

      for (let i = 0; i < batch.length; i++) {
        const parentId = batch[i]
        if (parentId !== null && visited.has(parentId)) continue
        visited.add(parentId)

        for (const node of results[i]) {
          snapshot.set(node.id, node)
          // 如果是文件夹，加入队列继续拉取
          if (node.is_folder) {
            queue.push(node.id)
          }
        }
      }
    }

    info(`Fetched ${snapshot.size} nodes from server`)
    return snapshot
  }

  /**
   * 拉取指定 parent_id 下的所有节点（分页直到取完）。
   */
  async _fetchAllInParent(parentId) {
    const all = []
    let page = 1
    const size = 200
    let total = Infinity

    while (all.length < total) {
      const data = await listFiles(parentId, page, size)
      total = data.total || 0
      all.push(...data.items)
      if (data.items.length < size) break
      page++
    }
    return all
  }
}

export const remotePoller = new RemotePoller()
