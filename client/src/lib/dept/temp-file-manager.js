/**
 * 部门网盘临时文件管理器。
 *
 * 核心原则（方案 6.2 / 6.3）：
 * - 双击文件 → 下载到系统临时目录 zhyCloudDeptCache/dept-<deptId>/ → 系统默认程序打开
 * - read_write：打开前先获取后端排他编辑锁（1.2.0），抢到才以读写打开；
 *   监听临时文件保存，去抖后自动覆盖回传，回传成功后释放锁（他人随即恢复可编辑）；
 *   编辑期间定时心跳续约，退出/关闭时兜底释放
 * - 抢锁失败（他人编辑中）或 read_only：落盘即置为只读（Office 类程序会强制走
 *   「另存为」），管理器绝不回传
 * - 退出客户端时尽力清空缓存；启动时删除超期（默认 7 天）残留
 *
 * 所有外部依赖均可通过 createTempFileManager(options) 注入，便于单测。
 */
import os from 'os'
import path from 'path'
import fs from 'fs'
import fsp from 'fs/promises'
import chokidar from 'chokidar'
import { shell } from 'electron'
import { computeMd5 } from '../sync/hasher.js'
import { downloadFile, lockAcquire, lockHeartbeat, lockRelease } from '../api/file.js'
import { uploadDeptFile } from '../api/department.js'

const DEFAULT_DEBOUNCE_MS = 800
const DEFAULT_TTL_MS = 7 * 24 * 3600 * 1000 // 7 天
const DEFAULT_HEARTBEAT_MS = 30 * 1000 // 后端锁 TTL 为 120s，30s 续约一次
const LOCK_CONFLICT_CODE = 3501
const RO_MODE = 0o444
const RW_MODE = 0o666

/** chokidar 生产实现：监听整个缓存目录，仅 change/add 上抛（原子保存=替换文件也能捕获）。 */
function defaultWatcherFactory(root, handler) {
  const w = chokidar.watch(root, {
    ignoreInitial: true,
    // 编辑器一次保存可能触发多次写，稳定 300ms 后再判定
    awaitWriteFinish: { stabilityThreshold: 300, pollInterval: 100 },
  })
  w.on('all', (event, filePath) => {
    if (event === 'change' || event === 'add') handler(event, filePath)
  })
  return {
    close: async () => w.close(),
  }
}

/**
 * @param {object} [options]
 * @param {string} [options.cacheRoot] 缓存根目录
 * @param {number} [options.debounceMs] 保存回传去抖毫秒
 * @param {(fileId:number, savePath:string)=>Promise<void>} [options.downloader]
 * @param {(filePath:string)=>Promise<void>|string} [options.opener] 系统打开
 * @param {(filePath:string)=>Promise<string>} [options.md5]
 * @param {(filePath:string, payload:object)=>Promise<object>} [options.uploader]
 * @param {(root:string, handler:(event:string,filePath:string)=>void)=>{close:Function}} [options.watcherFactory]
 * @param {{acquire:Function,heartbeat:Function,release:Function}} [options.locker] 排他锁接口
 * @param {number} [options.heartbeatMs] 锁心跳间隔
 * @param {(toast:{type:string,message:string})=>void} [options.onToast]
 * @param {()=>number} [options.now]
 */
export function createTempFileManager(options = {}) {
  const cacheRoot = options.cacheRoot || path.join(os.tmpdir(), 'zhyCloudDeptCache')
  const debounceMs = options.debounceMs ?? DEFAULT_DEBOUNCE_MS
  const heartbeatMs = options.heartbeatMs ?? DEFAULT_HEARTBEAT_MS
  const downloader = options.downloader || ((fileId, savePath) => downloadFile(fileId, savePath))
  const opener = options.opener || ((p) => shell.openPath(p))
  const md5 = options.md5 || computeMd5
  const uploader =
    options.uploader || ((filePath, payload) => uploadDeptFile(filePath, payload))
  const watcherFactory = options.watcherFactory || defaultWatcherFactory
  const locker = options.locker || {
    acquire: lockAcquire,
    heartbeat: lockHeartbeat,
    release: lockRelease,
  }
  const onToast = options.onToast || (() => {})
  const now = options.now || (() => Date.now())

  /** @type {Map<string, {fileId:number,deptId:number|null,parentId:number|null,fileName:string,access:string,baseline:string,uploading:boolean,dirty:boolean,timer:NodeJS.Timeout|null,readOnly:boolean,locked:boolean,lockedBy:string|null,lockTimer:NodeJS.Timeout|null}>} */
  const tracked = new Map()
  let watcher = null

  function deptDir(deptId) {
    return path.join(cacheRoot, `dept-${deptId}`)
  }

  /** 同名文件被多个部门文件打开时，加 (1)/(2) 后缀避让。 */
  function uniquePath(dir, fileName) {
    let candidate = path.join(dir, fileName)
    if (!tracked.has(candidate)) return candidate
    const ext = path.extname(fileName)
    const stem = path.basename(fileName, ext)
    let i = 1
    do {
      candidate = path.join(dir, `${stem} (${i})${ext}`)
      i += 1
    } while (tracked.has(candidate))
    return candidate
  }

  function ensureWatcher() {
    if (watcher) return watcher
    fs.mkdirSync(cacheRoot, { recursive: true })
    watcher = watcherFactory(cacheRoot, handleWatchEvent)
    return watcher
  }

  function handleWatchEvent(event, filePath) {
    const rec = tracked.get(filePath)
    if (!rec || rec.readOnly) return
    scheduleSync(rec)
  }

  function scheduleSync(rec) {
    if (rec.timer) clearTimeout(rec.timer)
    rec.timer = setTimeout(() => {
      rec.timer = null
      syncBack(rec)
    }, debounceMs)
    rec.timer.unref?.()
  }

  function stopHeartbeat(rec) {
    if (rec.lockTimer) {
      clearInterval(rec.lockTimer)
      rec.lockTimer = null
    }
  }

  function startHeartbeat(rec) {
    stopHeartbeat(rec)
    rec.lockTimer = setInterval(async () => {
      try {
        await locker.heartbeat(rec.fileId)
      } catch (e) {
        if (e?.code === LOCK_CONFLICT_CODE) {
          // 锁已易主（如被管理员强制释放后他人获取）：立即降级为只读
          await downgradeToReadOnly(rec, e.data?.user_name || null)
        }
        // 网络抖动等忽略，下个周期重试；最坏由后端 TTL 兜底
      }
    }, heartbeatMs)
    rec.lockTimer.unref?.()
  }

  async function downgradeToReadOnly(rec, holderName) {
    if (rec.readOnly) return
    stopHeartbeat(rec)
    rec.locked = false
    rec.access = 'read_only'
    rec.readOnly = true
    if (holderName) rec.lockedBy = holderName
    try {
      await fsp.chmod(rec.filePath, RO_MODE)
    } catch {
      // 文件占用等：权限位设置失败不影响后端写拦截
    }
    const who = holderName ? `被「${holderName}」锁定` : '编辑锁已失效'
    onToast({
      type: 'warning',
      message: `「${rec.fileName}」${who}，已转为只读，本次之后的修改不会回传`,
    })
  }

  /** 回传前确保持有锁；上一次保存已释放锁时按本次保存重新抢锁。成功返回 true。 */
  async function ensureLockedForSave(rec) {
    if (rec.locked) return true
    try {
      await locker.acquire(rec.fileId)
      rec.locked = true
      startHeartbeat(rec)
      return true
    } catch (e) {
      if (e?.code === LOCK_CONFLICT_CODE) {
        const who = e.data?.user_name ? `被「${e.data.user_name}」编辑` : '已被他人锁定'
        onToast({
          type: 'error',
          message: `「${rec.fileName}」${who}，本次修改未回传，请稍后重新打开文件`,
        })
        return false
      }
      throw e
    }
  }

  /** 保存成功后释放锁（需求：保存后他人立即恢复可编辑）。释放失败则保留锁并续心跳。 */
  async function releaseAfterSave(rec) {
    stopHeartbeat(rec)
    try {
      await locker.release(rec.fileId)
      rec.locked = false
    } catch {
      // 网络异常：锁可能仍在服务端，保留并继续续约，下次保存或退出时再释放
      startHeartbeat(rec)
    }
  }

  async function syncBack(rec) {
    if (rec.uploading) {
      // 回传中又有保存：标记脏，回传完成后再来一次
      rec.dirty = true
      return
    }
    rec.uploading = true
    try {
      let hash
      try {
        hash = await md5(rec.filePath)
      } catch {
        // 文件可能正被编辑器临时替换，忽略，等下一次事件
        return
      }
      if (hash === rec.baseline) return
      // 部门文件：保存即一次编辑事务，先确保持锁，防止与他人并发写
      if (rec.deptId != null && !(await ensureLockedForSave(rec))) return
      await uploader(rec.filePath, {
        departmentId: rec.deptId,
        parentId: rec.parentId,
        mode: 'overwrite',
        overwriteId: rec.fileId,
      })
      rec.baseline = hash
      if (rec.deptId != null && rec.locked) await releaseAfterSave(rec)
      onToast({ type: 'success', message: `「${rec.fileName}」修改已自动回传部门网盘` })
    } catch (e) {
      onToast({ type: 'error', message: `「${rec.fileName}」回传失败：${e.message}` })
    } finally {
      rec.uploading = false
      if (rec.dirty) {
        rec.dirty = false
        scheduleSync(rec)
      }
    }
  }

  return {
    cacheRoot,

    /**
     * 下载部门文件到临时目录并以系统程序打开。
     *
     * 部门读写文件先抢后端排他锁：抢到 → 读写打开 + 心跳；他人持锁 → 只读打开。
     * 只读权限 / 个人文件不抢锁。锁服务不可达（网络等）时不阻断打开，按读写放行，
     * 由后端写拦截与下次保存重试兜底。
     *
     * @param {object} node 服务端文件节点（非文件夹）
     * @returns {Promise<{filePath:string, access:string, locked:boolean, lockedBy:string|null}>}
     */
    async openForEdit(node) {
      const isDept = node.department_id != null
      let access = node.access || 'read_only'
      let locked = false
      let lockedBy = null

      if (isDept && access === 'read_write') {
        try {
          await locker.acquire(node.id)
          locked = true
        } catch (e) {
          if (e?.code === LOCK_CONFLICT_CODE) {
            // 他人正在编辑：降级只读
            access = 'read_only'
            lockedBy = e.data?.user_name || null
          } else {
            // 锁服务异常：放行读写但不持锁，保存时会再次尝试抢锁
            onToast({
              type: 'warning',
              message: `暂无法确认「${node.file_name}」的编辑锁状态：${e.message}`,
            })
          }
        }
      }

      const dir = deptDir(node.department_id ?? 'personal')
      await fsp.mkdir(dir, { recursive: true })
      const target = uniquePath(dir, node.file_name)

      // 覆盖上次会话残留（只读残留需先恢复写位，否则 Windows 下无法覆盖/删除）
      try {
        await fsp.chmod(target, RW_MODE)
      } catch {
        // 不存在
      }
      await downloader(node.id, target, {
        expectedSize: node.file_size ?? null,
        expectedHash: node.file_hash ?? null,
      })

      const baseline = await md5(target)

      const readOnly = access !== 'read_write'
      if (readOnly) {
        await fsp.chmod(target, RO_MODE)
      }

      const rec = {
        filePath: target,
        fileId: node.id,
        deptId: isDept ? node.department_id : null,
        parentId: node.parent_id ?? null,
        fileName: node.file_name,
        access,
        baseline,
        uploading: false,
        dirty: false,
        timer: null,
        readOnly,
        locked,
        lockedBy,
        lockTimer: null,
      }
      tracked.set(target, rec)

      ensureWatcher()
      if (locked) startHeartbeat(rec)
      await opener(target)
      return { filePath: target, access, locked, lockedBy }
    },

    /** 测试 / 内部：模拟一次外部保存事件。 */
    async _notifyChanged(filePath) {
      const rec = tracked.get(filePath)
      if (rec) scheduleSync(rec)
    },

    /** 是否有正在跟踪的临时文件。 */
    size() {
      return tracked.size
    },

    /**
     * 停止监听（不删除缓存文件）；持有的编辑锁全部尽力释放。
     */
    async stopWatching() {
      const pending = []
      for (const rec of tracked.values()) {
        if (rec.timer) clearTimeout(rec.timer)
        rec.timer = null
        stopHeartbeat(rec)
        if (rec.deptId != null && rec.locked) {
          pending.push(
            Promise.resolve(locker.release(rec.fileId)).catch(() => {
              // 退出时网络异常忽略，后端 TTL 兜底
            })
          )
        }
      }
      await Promise.all(pending)
      tracked.clear()
      if (watcher) {
        await watcher.close()
        watcher = null
      }
    },

    /**
     * 退出客户端时：停止监听并尽力清空缓存。
     * 仍被外部程序占用的文件删除会失败，忽略并留待下次启动超期清理。
     */
    async cleanupAll() {
      await this.stopWatching()
      try {
        await fsp.rm(cacheRoot, { recursive: true, force: true })
      } catch {
        // best-effort
      }
    },

    /**
     * 删除超期未再使用的临时文件，并清空变空的部门目录。
     * @param {number} [ttlMs]
     * @returns {Promise<number>} 删除的文件数
     */
    async cleanExpired(ttlMs = DEFAULT_TTL_MS) {
      let rootStat
      try {
        rootStat = await fsp.stat(cacheRoot)
      } catch {
        return 0 // 缓存目录尚不存在
      }
      if (!rootStat.isDirectory()) return 0

      const files = []
      const dirs = []
      const walk = async (d) => {
        const entries = await fsp.readdir(d, { withFileTypes: true })
        for (const entry of entries) {
          const full = path.join(d, entry.name)
          if (entry.isDirectory()) {
            dirs.push(full)
            await walk(full)
          } else {
            files.push(full)
          }
        }
      }
      await walk(cacheRoot)

      let removed = 0
      await Promise.all(
        files.map(async (f) => {
          try {
            const st = await fsp.stat(f)
            if (now() - st.mtimeMs > ttlMs) {
              try {
                await fsp.chmod(f, RW_MODE)
              } catch {
                // 权限不足时直接尝试删除
              }
              await fsp.unlink(f)
              removed += 1
            }
          } catch {
            // 文件被占用等：跳过
          }
        })
      )

      // 自底向上删除空目录
      dirs.sort((a, b) => b.length - a.length)
      for (const d of dirs) {
        try {
          await fsp.rmdir(d)
        } catch {
          // 非空，保留
        }
      }
      return removed
    },
  }
}

/** 进程级单例（主进程使用）。 */
let defaultManager = null

export function getTempManager() {
  if (!defaultManager) defaultManager = createTempFileManager()
  return defaultManager
}
