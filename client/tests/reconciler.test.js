/**
 * reconciler.test.js — 远端快照 ↔ 镜像 diff，生成下行同步任务
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import path from 'path'

vi.mock('../src/lib/mirror/mirror-db.js', () => {
  const remote = new Map()
  const localStates = new Map()
  return {
    getRemoteNode: (id) => remote.get(id),
    getAllRemoteNodes: () => Array.from(remote.values()),
    upsertRemoteNode: vi.fn((node, localPath) => remote.set(node.id, { ...node, local_path: localPath })),
    deleteRemoteNode: vi.fn((id) => remote.delete(id)),
    getLocalState: (p) => localStates.get(p),
    deleteLocalState: vi.fn((p) => localStates.delete(p)),
    __reset: (nodes = [], states = []) => {
      remote.clear()
      localStates.clear()
      nodes.forEach((n) => remote.set(n.id, { ...n }))
      states.forEach((s) => localStates.set(s.local_path, { ...s }))
    },
    __localStates: localStates,
  }
})
vi.mock('../src/lib/logger.js', () => ({ info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() }))
vi.mock('../src/lib/events.js', () => ({
  emit: vi.fn(),
  EVENTS: { LOG: 'log', STATE_CHANGE: 'state-change', PROGRESS: 'progress', CONFLICT: 'conflict' },
}))

import { reconcileRemote } from '../src/lib/sync/reconciler.js'
import {
  upsertRemoteNode,
  deleteRemoteNode,
  deleteLocalState,
  __reset,
  __localStates,
} from '../src/lib/mirror/mirror-db.js'
import { emit, EVENTS } from '../src/lib/events.js'

const ROOT = '/sync'

function snap(nodes) {
  return new Map(nodes.map((n) => [n.id, n]))
}

beforeEach(() => {
  vi.clearAllMocks()
  __reset()
})

describe('新增（镜像中无）', () => {
  it('远端新文件 → download 任务并写入镜像', () => {
    const tasks = reconcileRemote(
      snap([{ id: 10, file_name: 'a.txt', is_folder: 0, parent_id: null, upload_time: 'T1', file_size: 5 }]),
      ROOT,
      'keep-both'
    )
    expect(tasks).toEqual([{ type: 'download', serverId: 10, localPath: path.join(ROOT, 'a.txt') }])
    expect(upsertRemoteNode).toHaveBeenCalledWith(
      expect.objectContaining({ id: 10 }),
      path.join(ROOT, 'a.txt')
    )
  })

  it('远端新文件夹 → mkdir_local 任务', () => {
    const tasks = reconcileRemote(
      snap([{ id: 11, file_name: 'docs', is_folder: 1, parent_id: null, upload_time: 'T1', file_size: 0 }]),
      ROOT,
      'keep-both'
    )
    expect(tasks).toEqual([{ type: 'mkdir_local', localPath: path.join(ROOT, 'docs') }])
  })

  it('父目录已有镜像 → 新文件落在父目录下', () => {
    __reset([{ id: 5, file_name: 'docs', is_folder: 1, parent_id: null, upload_time: 'T1', file_size: 0, local_path: path.join(ROOT, 'docs') }])
    const tasks = reconcileRemote(
      snap([
        { id: 5, file_name: 'docs', is_folder: 1, parent_id: null, upload_time: 'T1', file_size: 0 },
        { id: 12, file_name: 'b.txt', is_folder: 0, parent_id: 5, upload_time: 'T1', file_size: 3 },
      ]),
      ROOT,
      'keep-both'
    )
    expect(tasks).toEqual([
      { type: 'download', serverId: 12, localPath: path.join(ROOT, 'docs', 'b.txt') },
    ])
  })
})

describe('改名 / 移动', () => {
  it('远端改名 → move_local 任务', () => {
    __reset([{ id: 10, file_name: 'old.txt', is_folder: 0, parent_id: null, upload_time: 'T1', file_size: 5, local_path: path.join(ROOT, 'old.txt') }])
    const tasks = reconcileRemote(
      snap([{ id: 10, file_name: 'new.txt', is_folder: 0, parent_id: null, upload_time: 'T1', file_size: 5 }]),
      ROOT,
      'keep-both'
    )
    expect(tasks).toEqual([
      {
        type: 'move_local',
        oldPath: path.join(ROOT, 'old.txt'),
        newPath: path.join(ROOT, 'new.txt'),
        serverId: 10,
      },
    ])
  })

  it('远端移动（parent 变更）→ move_local 到新父目录', () => {
    __reset([
      { id: 5, file_name: 'docs', is_folder: 1, parent_id: null, upload_time: 'T1', file_size: 0, local_path: path.join(ROOT, 'docs') },
      { id: 10, file_name: 'a.txt', is_folder: 0, parent_id: null, upload_time: 'T1', file_size: 5, local_path: path.join(ROOT, 'a.txt') },
    ])
    const tasks = reconcileRemote(
      snap([
        { id: 5, file_name: 'docs', is_folder: 1, parent_id: null, upload_time: 'T1', file_size: 0 },
        { id: 10, file_name: 'a.txt', is_folder: 0, parent_id: 5, upload_time: 'T1', file_size: 5 },
      ]),
      ROOT,
      'keep-both'
    )
    expect(tasks).toEqual([
      {
        type: 'move_local',
        oldPath: path.join(ROOT, 'a.txt'),
        newPath: path.join(ROOT, 'docs', 'a.txt'),
        serverId: 10,
      },
    ])
  })
})

describe('内容变更', () => {
  const mirrorNode = { id: 10, file_name: 'a.txt', is_folder: 0, parent_id: null, upload_time: 'T1', file_size: 5, local_path: path.join(ROOT, 'a.txt') }
  const changedNode = { id: 10, file_name: 'a.txt', is_folder: 0, parent_id: null, upload_time: 'T2', file_size: 10 }

  it('本地未修改 → 直接下载覆盖', () => {
    __reset([mirrorNode])
    const tasks = reconcileRemote(snap([changedNode]), ROOT, 'keep-both')
    expect(tasks).toEqual([
      { type: 'download', serverId: 10, localPath: path.join(ROOT, 'a.txt'), overwrite: true },
    ])
  })

  it('本地也修改（pending_upload）+ keep-both → 下载到冲突副本路径', () => {
    __reset([mirrorNode], [{ local_path: path.join(ROOT, 'a.txt'), state: 'pending_upload' }])
    const tasks = reconcileRemote(snap([changedNode]), ROOT, 'keep-both')
    expect(tasks.length).toBe(1)
    expect(tasks[0].type).toBe('download')
    // 冲突副本命名规则：词干 + " (服务器冲突 时间戳)" + 扩展名
    expect(tasks[0].localPath).toBe('/sync/a (服务器冲突 ' + Date.now() + ').txt')
    expect(emit).toHaveBeenCalledWith(EVENTS.CONFLICT, expect.objectContaining({ serverNode: changedNode }))
  })

  it('本地也修改 + last-write-wins → 不生成任务（保留本地待上行）', () => {
    __reset([mirrorNode], [{ local_path: path.join(ROOT, 'a.txt'), state: 'pending_upload' }])
    const tasks = reconcileRemote(snap([changedNode]), ROOT, 'last-write-wins')
    expect(tasks).toEqual([])
  })
})

describe('远端删除', () => {
  it('镜像有、远端无 → delete_local 任务并清理镜像', () => {
    __reset(
      [{ id: 10, file_name: 'a.txt', is_folder: 0, parent_id: null, upload_time: 'T1', file_size: 5, local_path: path.join(ROOT, 'a.txt') }],
      [{ local_path: path.join(ROOT, 'a.txt'), server_id: 10 }]
    )
    const tasks = reconcileRemote(snap([]), ROOT, 'keep-both')
    expect(tasks).toEqual([{ type: 'delete_local', localPath: path.join(ROOT, 'a.txt'), isFolder: 0 }])
    expect(deleteRemoteNode).toHaveBeenCalledWith(10)
    expect(deleteLocalState).toHaveBeenCalledWith(path.join(ROOT, 'a.txt'))
  })

  it('镜像节点无 local_path → 只清理镜像，不生成删除任务', () => {
    __reset([{ id: 10, file_name: 'a.txt', is_folder: 0, parent_id: null, upload_time: 'T1', file_size: 5, local_path: null }])
    const tasks = reconcileRemote(snap([]), ROOT, 'keep-both')
    expect(tasks).toEqual([])
    expect(deleteRemoteNode).toHaveBeenCalledWith(10)
  })
})

describe('无变化', () => {
  it('镜像与快照一致 → 无任务', () => {
    __reset([
      { id: 10, file_name: 'a.txt', is_folder: 0, parent_id: null, upload_time: 'T1', file_size: 5, local_path: path.join(ROOT, 'a.txt') },
    ])
    const tasks = reconcileRemote(
      snap([{ id: 10, file_name: 'a.txt', is_folder: 0, parent_id: null, upload_time: 'T1', file_size: 5 }]),
      ROOT,
      'keep-both'
    )
    expect(tasks).toEqual([])
  })

  it('无变化但镜像缺 local_path → 补写路径', () => {
    __reset([{ id: 10, file_name: 'a.txt', is_folder: 0, parent_id: null, upload_time: 'T1', file_size: 5, local_path: null }])
    const tasks = reconcileRemote(
      snap([{ id: 10, file_name: 'a.txt', is_folder: 0, parent_id: null, upload_time: 'T1', file_size: 5 }]),
      ROOT,
      'keep-both'
    )
    expect(tasks).toEqual([])
    expect(upsertRemoteNode).toHaveBeenCalledWith(
      expect.objectContaining({ id: 10 }),
      path.join(ROOT, 'a.txt')
    )
  })
})
