/**
 * 本地文件监听器：chokidar 封装、事件去抖、重命名关联。
 * 事件：add / change / unlink / addDir / unlinkDir
 * 去抖：500ms 合并同一文件的多次 change。
 * 重命名关联：unlink + add 在 3s 窗口内配对。
 */
import chokidar from 'chokidar'
import path from 'path'
import { getFileInfo } from './hasher.js'
import { getLocalState } from '../mirror/mirror-db.js'
import { localPathToServerId, localParentToServerId } from '../paths.js'
import { info, warn } from '../logger.js'

const DEBOUNCE_MS = 500
const RENAME_WINDOW_MS = 3000

class LocalWatcher {
  constructor() {
    this.watcher = null
    this.syncRoot = ''
    this.callbacks = {}
    this.debounceTimers = new Map()
    this.renameCandidates = [] // { path, stats, serverId, ts }
  }

  on(event, cb) {
    this.callbacks[event] = cb
  }

  start(syncRoot) {
    this.syncRoot = syncRoot
    this.watcher = chokidar.watch(syncRoot, {
      ignored: /(^|[/\\])\./, // 忽略隐藏文件/目录
      ignoreInitial: true,
      persistent: true,
      awaitWriteFinish: { stabilityThreshold: 1000, pollInterval: 200 },
    })

    this.watcher.on('add', (p) => this._onAdd(p))
    this.watcher.on('change', (p) => this._onChange(p))
    this.watcher.on('unlink', (p) => this._onUnlink(p))
    this.watcher.on('addDir', (p) => this._onAddDir(p))
    this.watcher.on('unlinkDir', (p) => this._onUnlinkDir(p))
    this.watcher.on('error', (e) => warn('Watcher error:', e))

    info(`Local watcher started for: ${syncRoot}`)
  }

  stop() {
    if (this.watcher) {
      this.watcher.close()
      this.watcher = null
    }
    // 清理去抖定时器
    this.debounceTimers.forEach((t) => clearTimeout(t))
    this.debounceTimers.clear()
  }

  _debounce(key, fn) {
    if (this.debounceTimers.has(key)) {
      clearTimeout(this.debounceTimers.get(key))
    }
    this.debounceTimers.set(key, setTimeout(() => {
      this.debounceTimers.delete(key)
      fn()
    }, DEBOUNCE_MS))
  }

  // ---- 文件事件 ----

  _onAdd(localPath) {
    this._debounce(`add:${localPath}`, async () => {
      // 先尝试重命名关联
      if (await this._tryRenameAssociation(localPath)) return
      // 普通新增
      const serverParentId = localParentToServerId(this.syncRoot, path.dirname(localPath))
      this.callbacks.onAdd?.(localPath, serverParentId)
    })
  }

  _onChange(localPath) {
    this._debounce(`change:${localPath}`, async () => {
      try {
        const info = await getFileInfo(localPath)
        const state = getLocalState(localPath)
        // 内容未变则跳过
        if (state && state.local_md5 === info.md5) return
        this.callbacks.onChange?.(localPath, info, state)
      } catch (e) {
        warn(`change handler error: ${e.message}`)
      }
    })
  }

  _onUnlink(localPath) {
    // 放入重命名待关联队列
    this.renameCandidates.push({
      path: localPath,
      ts: Date.now(),
      serverId: localPathToServerId(localPath),
    })
    // 超时后判定为删除
    this._debounce(`unlink:${localPath}`, () => {
      const idx = this.renameCandidates.findIndex((c) => c.path === localPath)
      if (idx >= 0) {
        this.renameCandidates.splice(idx, 1)
        this.callbacks.onDelete?.(localPath)
      }
    })
    // 清理过期候选
    this._cleanupRenameCandidates()
  }

  // ---- 目录事件 ----

  _onAddDir(localPath) {
    this._debounce(`adddir:${localPath}`, () => {
      const serverParentId = localParentToServerId(this.syncRoot, path.dirname(localPath))
      this.callbacks.onAddDir?.(localPath, serverParentId)
    })
  }

  _onUnlinkDir(localPath) {
    this._debounce(`unlinkdir:${localPath}`, () => {
      this.callbacks.onDeleteDir?.(localPath)
    })
  }

  // ---- 重命名关联 ----

  async _tryRenameAssociation(newPath) {
    this._cleanupRenameCandidates()
    if (this.renameCandidates.length === 0) return false

    try {
      const newInfo = await getFileInfo(newPath)
      // 在候选队列中找 size + md5 匹配
      for (let i = this.renameCandidates.length - 1; i >= 0; i--) {
        const candidate = this.renameCandidates[i]
        try {
          // 候选的 md5 从 mirror 的 local_state 读取
          const state = getLocalState(candidate.path)
          if (state && state.local_size === newInfo.size && state.local_md5 === newInfo.md5) {
            // 匹配成功：重命名/移动
            this.renameCandidates.splice(i, 1)
            const isNewPathInSameDir = path.dirname(newPath) === path.dirname(candidate.path)
            if (isNewPathInSameDir) {
              this.callbacks.onRename?.(candidate.path, newPath, candidate.serverId)
            } else {
              const newParentId = localParentToServerId(this.syncRoot, path.dirname(newPath))
              this.callbacks.onMove?.(candidate.path, newPath, candidate.serverId, newParentId)
            }
            return true
          }
        } catch {
          // 候选文件已删除，跳过
        }
      }
    } catch {
      // 新文件无法读取
    }
    return false
  }

  _cleanupRenameCandidates() {
    const now = Date.now()
    this.renameCandidates = this.renameCandidates.filter((c) => now - c.ts < RENAME_WINDOW_MS)
  }
}

export const localWatcher = new LocalWatcher()
