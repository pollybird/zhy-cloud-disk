/**
 * dept-temp-manager.test.js — 临时下载 / 只读打开 / 保存自动回传 / 清理
 *
 * 使用真实临时目录落盘（fs 行为真实），下载/打开/上传/监听器全部注入假实现。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import os from 'os'
import path from 'path'
import fs from 'fs'
import fsp from 'fs/promises'
import { computeMd5 } from '../src/lib/sync/hasher.js'
import { createTempFileManager } from '../src/lib/dept/temp-file-manager.js'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

let cacheRoot
let watcherHandler
let watcherClose

function makeManager(overrides = {}) {
  const opener = vi.fn(async () => '')
  const uploader = vi.fn(async () => ({ success: [{}] }))
  const onToast = vi.fn()
  const watcherFactory = vi.fn((_root, handler) => {
    watcherHandler = handler
    watcherClose = vi.fn(async () => {})
    return { close: watcherClose }
  })
  const downloader = vi.fn(async (_id, savePath) => {
    await fsp.writeFile(savePath, 'v1-content')
  })
  // 默认 locker：全部成功（1.2.0 排他编辑锁）
  const locker = {
    acquire: vi.fn(async () => ({ locked: true, held_by_me: true })),
    heartbeat: vi.fn(async () => ({})),
    release: vi.fn(async () => ({ locked: false })),
  }
  const manager = createTempFileManager({
    cacheRoot,
    debounceMs: 30,
    heartbeatMs: 60000,
    downloader,
    opener,
    uploader,
    onToast,
    watcherFactory,
    locker,
    md5: computeMd5,
    ...overrides,
  })
  return { manager, opener, uploader, onToast, watcherFactory, downloader, locker }
}

const node = (id, access = 'read_write', fileName = 'a.txt') => ({
  id,
  department_id: 7,
  parent_id: null,
  file_name: fileName,
  access,
})

beforeEach(() => {
  cacheRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'zhy-dept-test-'))
  watcherHandler = null
})

afterEach(async () => {
  await fsp.rm(cacheRoot, { recursive: true, force: true }).catch(() => {})
})

describe('openForEdit', () => {
  it('read_write：下载到 dept-<id> 目录并以系统程序打开', async () => {
    const { manager, opener } = makeManager()
    const ret = await manager.openForEdit(node(1))
    expect(ret.access).toBe('read_write')
    expect(ret.filePath.replaceAll('\\', '/')).toContain('dept-7/a.txt')
    expect(opener).toHaveBeenCalledTimes(1)
    await expect(fsp.access(ret.filePath)).resolves.toBeUndefined()
  })

  it('read_only：文件置只读位，保存事件不触发回传', async () => {
    const { manager, uploader } = makeManager()
    const ret = await manager.openForEdit(node(2, 'read_only'))
    const st = await fsp.stat(ret.filePath)
    expect(st.mode & 0o200).toBe(0) // 所有者写位关闭

    watcherHandler('change', ret.filePath)
    await sleep(80)
    expect(uploader).not.toHaveBeenCalled()
  })

  it('同部门同名文件同时打开 → 自动加序号避让', async () => {
    const { manager } = makeManager()
    const first = await manager.openForEdit(node(1, 'read_write', '报告.docx'))
    const second = await manager.openForEdit(node(2, 'read_write', '报告.docx'))
    expect(second.filePath).not.toBe(first.filePath)
    expect(path.basename(second.filePath)).toBe('报告 (1).docx')
  })
})

describe('保存自动回传', () => {
  it('文件内容变化 → 去抖后以 overwrite 覆盖回传并提示成功', async () => {
    const { manager, uploader, onToast } = makeManager()
    const ret = await manager.openForEdit(node(1))

    await fsp.appendFile(ret.filePath, '\nedited')
    watcherHandler('change', ret.filePath)
    await sleep(100)

    expect(uploader).toHaveBeenCalledTimes(1)
    expect(uploader).toHaveBeenCalledWith(
      ret.filePath,
      expect.objectContaining({
        departmentId: 7,
        parentId: null,
        mode: 'overwrite',
        overwriteId: 1,
      })
    )
    expect(onToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'success' })
    )

    // 内容未变的重复事件不再上传
    watcherHandler('change', ret.filePath)
    await sleep(80)
    expect(uploader).toHaveBeenCalledTimes(1)
  })

  it('回传期间再次保存：标记脏，回传完成后补传一次（不丢修改）', async () => {
    let releaseUpload
    const gated = vi.fn(
      () =>
        new Promise((resolve) => {
          releaseUpload = () => resolve({ success: [{}] })
        })
    )
    const { manager } = makeManager({ uploader: gated })
    const ret = await manager.openForEdit(node(1))

    // 第一次保存 → 进入回传中
    await fsp.writeFile(ret.filePath, 'version-2')
    watcherHandler('change', ret.filePath)
    await sleep(70)
    expect(gated).toHaveBeenCalledTimes(1)

    // 回传未完成又保存
    await fsp.writeFile(ret.filePath, 'version-3')
    watcherHandler('change', ret.filePath)
    await sleep(70)
    expect(gated).toHaveBeenCalledTimes(1) // 进行中不重复发起

    releaseUpload()
    await sleep(100)
    expect(gated).toHaveBeenCalledTimes(2) // 补传
  })

  it('回传失败 → 错误提示，不更新基线（下次保存可再次尝试）', async () => {
    const failing = vi.fn().mockRejectedValueOnce(new Error('403'))
    const { manager, onToast } = makeManager({ uploader: failing })
    const ret = await manager.openForEdit(node(1))

    await fsp.appendFile(ret.filePath, 'x')
    watcherHandler('change', ret.filePath)
    await sleep(90)
    expect(onToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'error', message: expect.stringContaining('403') })
    )

    // 再次保存仍可发起（基线未变）
    await fsp.appendFile(ret.filePath, 'y')
    watcherHandler('change', ret.filePath)
    await sleep(90)
    expect(failing).toHaveBeenCalledTimes(2)
  })
})

describe('缓存清理', () => {
  it('cleanupAll：关闭监听并删除整个缓存目录', async () => {
    const { manager } = makeManager()
    const ret = await manager.openForEdit(node(1))
    expect(manager.size()).toBe(1)

    await manager.cleanupAll()
    expect(watcherClose).toHaveBeenCalled()
    await expect(fsp.access(ret.filePath)).rejects.toThrow()
    await expect(fsp.access(cacheRoot)).rejects.toThrow()
  })

  it('cleanExpired：删除超期文件与空目录，保留新文件', async () => {
    const { manager } = makeManager()
    const ret = await manager.openForEdit(node(1, 'read_write', 'new.txt'))

    // 构造 10 天前的旧文件 + 空部门目录
    const oldFile = path.join(cacheRoot, 'dept-9', 'old.txt')
    await fsp.mkdir(path.dirname(oldFile), { recursive: true })
    await fsp.writeFile(oldFile, 'old')
    const emptyDir = path.join(cacheRoot, 'dept-99')
    await fsp.mkdir(emptyDir, { recursive: true })
    const tenDaysAgo = new Date(Date.now() - 10 * 24 * 3600 * 1000)
    await fsp.utimes(oldFile, tenDaysAgo, tenDaysAgo)

    const removed = await manager.cleanExpired(7 * 24 * 3600 * 1000)
    expect(removed).toBe(1)
    await expect(fsp.access(oldFile)).rejects.toThrow()
    await expect(fsp.access(emptyDir)).rejects.toThrow() // 空目录被清
    await expect(fsp.access(ret.filePath)).resolves.toBeUndefined()
  })

  it('缓存目录不存在时 cleanExpired 安全返回 0', async () => {
    const { manager } = makeManager()
    await fsp.rm(cacheRoot, { recursive: true, force: true })
    await expect(manager.cleanExpired()).resolves.toBe(0)
  })
})

describe('1.2.0 排他编辑锁', () => {
  const conflictError = (name = 'lockA') => {
    const e = new Error(`文件正被「${name}」编辑`)
    e.code = 3501
    e.data = { user_id: 9, user_name: name }
    return e
  }

  it('读写部门文件：打开前 acquire，返回 locked=true', async () => {
    const { manager, locker } = makeManager()
    const ret = await manager.openForEdit(node(11))
    expect(locker.acquire).toHaveBeenCalledWith(11)
    expect(ret.locked).toBe(true)
    expect(ret.access).toBe('read_write')
  })

  it('只读权限文件：不抢锁，按只读打开', async () => {
    const { manager, locker } = makeManager()
    const ret = await manager.openForEdit(node(12, 'read_only'))
    expect(locker.acquire).not.toHaveBeenCalled()
    expect(ret.locked).toBe(false)
    expect(ret.access).toBe('read_only')
  })

  it('他人持锁（3501）：降级只读打开，返回 lockedBy，不回传', async () => {
    const locker = {
      acquire: vi.fn(async () => {
        throw conflictError('张三')
      }),
      heartbeat: vi.fn(),
      release: vi.fn(),
    }
    const { manager, uploader } = makeManager({ locker })
    const ret = await manager.openForEdit(node(13))
    expect(ret.access).toBe('read_only')
    expect(ret.locked).toBe(false)
    expect(ret.lockedBy).toBe('张三')
    const st = await fsp.stat(ret.filePath)
    expect(st.mode & 0o200).toBe(0)

    watcherHandler('change', ret.filePath)
    await sleep(80)
    expect(uploader).not.toHaveBeenCalled()
  })

  it('锁服务网络异常：不阻断打开（读写放行），但不启动心跳', async () => {
    const locker = {
      acquire: vi.fn(async () => {
        throw new Error('Network Error')
      }),
      heartbeat: vi.fn(),
      release: vi.fn(),
    }
    const { manager, onToast } = makeManager({ locker })
    const ret = await manager.openForEdit(node(14))
    expect(ret.access).toBe('read_write')
    expect(ret.locked).toBe(false)
    expect(onToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'warning' })
    )
  })

  it('个人文件（无 department_id）：不抢锁', async () => {
    const { manager, locker } = makeManager()
    const ret = await manager.openForEdit({ ...node(15), department_id: null })
    expect(locker.acquire).not.toHaveBeenCalled()
    expect(ret.locked).toBe(false)
  })

  it('保存回传成功后立即 release（他人恢复可编辑）', async () => {
    const { manager, uploader, locker } = makeManager()
    const ret = await manager.openForEdit(node(21))

    await fsp.appendFile(ret.filePath, '\nedited-1')
    watcherHandler('change', ret.filePath)
    await sleep(90)

    expect(uploader).toHaveBeenCalledTimes(1)
    expect(locker.release).toHaveBeenCalledTimes(1)
    expect(locker.release).toHaveBeenCalledWith(21)
  })

  it('释放后再次编辑：保存前重新抢锁，冲突则不回传并提示', async () => {
    const { manager, uploader, locker } = makeManager()
    const ret = await manager.openForEdit(node(22))

    // 第一次保存：抢锁→上传→释放
    await fsp.writeFile(ret.filePath, 'v2')
    watcherHandler('change', ret.filePath)
    await sleep(90)
    expect(locker.release).toHaveBeenCalledTimes(1)

    // 第二次保存：锁已被他人获取
    locker.acquire.mockReset()
    locker.acquire.mockRejectedValueOnce(conflictError('李四'))
    await fsp.writeFile(ret.filePath, 'v3')
    watcherHandler('change', ret.filePath)
    await sleep(90)
    expect(uploader).toHaveBeenCalledTimes(1) // 第二次未上传
  })

  it('心跳发现锁易主（3501）：文件降级只读，后续修改不回传', async () => {
    const locker = {
      acquire: vi.fn(async () => ({})),
      heartbeat: vi.fn(async () => {
        throw conflictError('王五')
      }),
      release: vi.fn(async () => ({})),
    }
    const { manager, uploader } = makeManager({ locker, heartbeatMs: 25 })
    const ret = await manager.openForEdit(node(23))
    expect(ret.access).toBe('read_write')

    await sleep(90)
    const st = await fsp.stat(ret.filePath)
    expect(st.mode & 0o200).toBe(0) // 已置只读

    await fsp.chmod(ret.filePath, 0o666) // 即使本地能写
    await fsp.appendFile(ret.filePath, 'late-edit')
    watcherHandler('change', ret.filePath)
    await sleep(80)
    expect(uploader).not.toHaveBeenCalled()
  })

  it('stopWatching/cleanupAll：兜底释放持有的锁，只读打开的不释放', async () => {
    const lockedLocker = {
      acquire: vi.fn(async () => ({})),
      heartbeat: vi.fn(async () => ({})),
      release: vi.fn(async () => ({})),
    }
    const m1 = makeManager({ locker: lockedLocker })
    await m1.manager.openForEdit(node(31))

    const blockedLocker = {
      acquire: vi.fn(async () => {
        throw conflictError('张三')
      }),
      heartbeat: vi.fn(),
      release: vi.fn(),
    }
    const m2 = makeManager({ locker: blockedLocker })
    await m2.manager.openForEdit(node(32))

    await Promise.all([m1.manager.stopWatching(), m2.manager.stopWatching()])
    expect(lockedLocker.release).toHaveBeenCalledTimes(1)
    expect(lockedLocker.release).toHaveBeenCalledWith(31)
    expect(blockedLocker.release).not.toHaveBeenCalled()
  })

  it('编辑器关闭探测：连续未占用（打开成功）→ 自动释放锁并停止心跳', async () => {
    // probeOpener 注入为「总能打开」→ 模拟编辑器已关闭（句柄未独占）
    const probeOpener = vi.fn(async () => ({ close: async () => {} }))
    const { manager, locker } = makeManager({ heartbeatMs: 25, probeOpener })
    await manager.openForEdit(node(41))
    expect(locker.release).not.toHaveBeenCalled()

    // 25ms × 连续 2 轮未占用 → finalizeClosed（留 90ms 余量）
    await sleep(90)
    expect(locker.release).toHaveBeenCalledTimes(1)
    expect(locker.release).toHaveBeenCalledWith(41)

    const calls = locker.heartbeat.mock.calls.length
    expect(calls).toBeGreaterThan(0)
    await sleep(60)
    expect(locker.heartbeat.mock.calls.length).toBe(calls) // 心跳已停
  })

  it('编辑器占用中（独占打开失败 EBUSY）→ 不释放锁，心跳持续续约', async () => {
    // probeOpener 抛 EBUSY → 模拟 Office/WPS 仍持有文件
    const busyError = Object.assign(new Error('EBUSY: resource busy'), { code: 'EBUSY' })
    const probeOpener = vi.fn(async () => {
      throw busyError
    })
    const { manager, locker } = makeManager({ heartbeatMs: 25, probeOpener })
    await manager.openForEdit(node(42))

    await sleep(120)
    expect(locker.release).not.toHaveBeenCalled()
    expect(locker.heartbeat.mock.calls.length).toBeGreaterThanOrEqual(3)
  })

  it('探测判定关闭后再次保存：重新抢锁并回传成功', async () => {
    const probeOpener = vi.fn(async () => ({ close: async () => {} }))
    const { manager, uploader, locker } = makeManager({ heartbeatMs: 25, probeOpener })
    const ret = await manager.openForEdit(node(43))

    await sleep(90) // 探测判关闭 → release
    expect(locker.release).toHaveBeenCalledWith(43)
    locker.acquire.mockClear()

    // 编辑器（误判场景）之后又保存：ensureLockedForSave 重抢锁 → 回传
    await fsp.appendFile(ret.filePath, '\nlate-save')
    watcherHandler('change', ret.filePath)
    await sleep(90)
    expect(locker.acquire).toHaveBeenCalledWith(43)
    expect(uploader).toHaveBeenCalledTimes(1)
    expect(locker.release).toHaveBeenCalledTimes(2) // 回传成功后再次释放
  })

  it('回传中 / 防抖期间探测保守视为占用（不提前释放）', async () => {
    // 用 gate uploader 让第一次回传长时间进行中
    let releaseUpload
    const gated = vi.fn(
      () =>
        new Promise((resolve) => {
          releaseUpload = () => resolve({ success: [{}] })
        })
    )
    const probeOpener = vi.fn(async () => ({ close: async () => {} }))
    const { manager, locker } = makeManager({
      heartbeatMs: 25,
      probeOpener,
      uploader: gated,
    })
    const ret = await manager.openForEdit(node(44))

    // 保存 → 进入 uploading（回传挂起）；探测应视为占用 → 不 finalize
    await fsp.appendFile(ret.filePath, '\nsaving')
    watcherHandler('change', ret.filePath)
    await sleep(90)
    expect(gated).toHaveBeenCalledTimes(1)
    expect(locker.release).not.toHaveBeenCalled()

    releaseUpload()
    await sleep(80)
    expect(locker.release).toHaveBeenCalledTimes(1) // 回传完成后正常释放
  })
})
