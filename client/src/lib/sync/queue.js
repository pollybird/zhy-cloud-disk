/**
 * 串行任务队列：所有写操作串行执行，避免并发冲突。
 * 任务类型：upload | download | delete_remote | delete_local | rename_remote | move_remote | rename_local | move_local
 */
import path from 'path'
import { error } from '../logger.js'
import { addSyncLog } from '../mirror/mirror-db.js'
import { emit, EVENTS } from '../events.js'

class SyncQueue {
  constructor() {
    this.tasks = []
    this.running = false
    this.currentTask = null
    this.handlers = {}
    this.lockedIds = new Set() // 正在处理的 server_id
  }

  register(type, handler) {
    this.handlers[type] = handler
  }

  add(task) {
    // 去重：同一 server_id 的同类型任务不重复入队
    if (task.serverId && this.lockedIds.has(task.serverId) && task.type === this.currentTask?.type) {
      return
    }
    this.tasks.push(task)
    this._drain()
  }

  addAll(tasks) {
    this.tasks.push(...tasks)
    this._drain()
  }

  size() {
    return this.tasks.length + (this.currentTask ? 1 : 0)
  }

  clear() {
    this.tasks = []
  }

  async _drain() {
    if (this.running) return
    this.running = true

    while (this.tasks.length > 0) {
      this.currentTask = this.tasks.shift()
      const task = this.currentTask
      if (task.serverId) this.lockedIds.add(task.serverId)

      try {
        const handler = this.handlers[task.type]
        if (!handler) {
          error(`No handler for task type: ${task.type}`)
          continue
        }
        await handler(task)
      } catch (e) {
        error(`Task ${task.type} failed: ${e.message}`, task)
        // 重试 3 次
        if (!task.retries) task.retries = 0
        task.retries++
        if (task.retries <= 3) {
          const delay = 2000 * Math.pow(2, task.retries - 1)
          await new Promise((r) => setTimeout(r, delay))
          this.tasks.unshift(task)
        } else {
          // 重试耗尽：记录失败日志并广播
          const entry = {
            action: task.logAction || task.type,
            fileName: task.logFileName || (task.localPath ? path.basename(task.localPath) : null),
            localPath: task.localPath,
            status: 'failed',
            message: `重试 ${task.retries - 1} 次后仍失败：${e.message}`,
          }
          addSyncLog(entry)
          emit(EVENTS.LOG, entry)
        }
      } finally {
        if (task.serverId) this.lockedIds.delete(task.serverId)
        this.currentTask = null
      }
    }

    this.running = false
  }
}

export const queue = new SyncQueue()
