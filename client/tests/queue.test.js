/**
 * queue.test.js — 串行任务队列：顺序执行 / 去重 / 重试 / 重试耗尽记日志
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('../src/lib/mirror/mirror-db.js', () => ({
  addSyncLog: vi.fn(),
}))
vi.mock('../src/lib/logger.js', () => ({
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
}))
vi.mock('../src/lib/events.js', () => ({
  emit: vi.fn(),
  EVENTS: { LOG: 'log', STATE_CHANGE: 'state-change', PROGRESS: 'progress', CONFLICT: 'conflict' },
}))

import { queue } from '../src/lib/sync/queue.js'
import { addSyncLog } from '../src/lib/mirror/mirror-db.js'
import { emit, EVENTS } from '../src/lib/events.js'
import { error } from '../src/lib/logger.js'

function flush() {
  return new Promise((r) => setTimeout(r, 0))
}

beforeEach(() => {
  vi.clearAllMocks()
  queue.clear()
  queue.currentTask = null
  queue.lockedIds.clear()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('串行执行', () => {
  it('任务按入队顺序依次执行，不并发', async () => {
    const events = []
    let resolvers = []
    queue.register('t1', () => new Promise((r) => resolvers.push(r)).then(() => events.push(`end:${events.length}`)))

    queue.add({ type: 't1' })
    queue.add({ type: 't1' })
    queue.add({ type: 't1' })
    await flush()
    // 第一个任务已开始且未完成
    expect(events).toEqual([])

    resolvers[0]()
    await flush()
    expect(events.length).toBe(1)

    resolvers[1]()
    await flush()
    expect(events.length).toBe(2)

    resolvers[2]()
    await flush()
    await vi.waitFor(() => expect(queue.size()).toBe(0))
    expect(events.length).toBe(3)
  })
})

describe('去重', () => {
  it('同 serverId 同类型任务在处理中不重复入队', async () => {
    let release
    queue.register('upload', () => new Promise((r) => (release = r)))

    queue.add({ type: 'upload', serverId: 7 })
    queue.add({ type: 'upload', serverId: 7 }) // 被去重
    queue.add({ type: 'upload', serverId: 7 }) // 被去重
    expect(queue.size()).toBe(1)

    release()
    await vi.waitFor(() => expect(queue.size()).toBe(0))
  })

  it('同 serverId 不同类型任务不去重', async () => {
    let release
    queue.register('upload', () => new Promise((r) => (release = r)))
    queue.register('delete_remote', () => Promise.resolve())

    queue.add({ type: 'upload', serverId: 7 })
    queue.add({ type: 'delete_remote', serverId: 7 })
    expect(queue.size()).toBe(2)

    release()
    await vi.waitFor(() => expect(queue.size()).toBe(0))
  })
})

describe('失败重试', () => {
  it('失败后按 2s/4s/8s 退避重试，第 4 次成功则不再记录失败日志', async () => {
    vi.useFakeTimers()
    let calls = 0
    queue.register('flaky', () => {
      calls++
      if (calls < 4) return Promise.reject(new Error('boom'))
      return Promise.resolve()
    })

    queue.add({ type: 'flaky', localPath: '/x/f.txt' })
    await vi.runAllTimersAsync()
    vi.useRealTimers()
    await flush()

    expect(calls).toBe(4)
    expect(addSyncLog).not.toHaveBeenCalled()
  })

  it('重试耗尽后记录失败日志并广播 LOG 事件', async () => {
    vi.useFakeTimers()
    queue.register('doomed', () => Promise.reject(new Error('always fail')))

    queue.add({ type: 'doomed', localPath: '/x/g.txt', logAction: 'upload' })
    await vi.runAllTimersAsync()
    vi.useRealTimers()
    await flush()

    // 初次 + 3 次重试 = 4 次
    expect(error).toHaveBeenCalledTimes(4)
    expect(addSyncLog).toHaveBeenCalledWith(
      expect.objectContaining({
        action: 'upload',
        fileName: 'g.txt',
        localPath: '/x/g.txt',
        status: 'failed',
        message: expect.stringContaining('always fail'),
      })
    )
    expect(emit).toHaveBeenCalledWith(EVENTS.LOG, expect.objectContaining({ status: 'failed' }))
  })

  it('无 localPath 的任务失败日志 fileName 为 null', async () => {
    vi.useFakeTimers()
    queue.register('noPath', () => Promise.reject(new Error('x')))
    queue.add({ type: 'noPath' })
    await vi.runAllTimersAsync()
    vi.useRealTimers()
    await flush()

    expect(addSyncLog).toHaveBeenCalledWith(
      expect.objectContaining({ fileName: null, action: 'noPath' })
    )
  })

  it('未注册类型的任务：记录错误并跳过，不崩溃', async () => {
    queue.add({ type: 'unknown_type' })
    await vi.waitFor(() => expect(queue.size()).toBe(0))
    expect(error).toHaveBeenCalledWith(expect.stringContaining('No handler'))
  })
})
