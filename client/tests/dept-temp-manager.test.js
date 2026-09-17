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
  const manager = createTempFileManager({
    cacheRoot,
    debounceMs: 30,
    downloader,
    opener,
    uploader,
    onToast,
    watcherFactory,
    md5: computeMd5,
    ...overrides,
  })
  return { manager, opener, uploader, onToast, watcherFactory, downloader }
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
