/**
 * paths.test.js — 服务端 parent_id 树 ↔ 本地路径 双向映射
 * mirror-db 为 mock（better-sqlite3 是 Electron ABI，Node 下不可加载）
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import path from 'path'

vi.mock('../src/lib/mirror/mirror-db.js', () => ({
  getRemoteNode: vi.fn(),
  getRemoteNodeByPath: vi.fn(),
  getLocalState: vi.fn(),
}))

import { getRemoteNode, getRemoteNodeByPath, getLocalState } from '../src/lib/mirror/mirror-db.js'
import { serverPathToLocal, localPathToServerId, localParentToServerId } from '../src/lib/paths.js'

beforeEach(() => {
  vi.clearAllMocks()
})

describe('serverPathToLocal', () => {
  const root = '/home/u/zhyCloud'

  it('parent_id 为 null → 映射到同步根目录', () => {
    expect(serverPathToLocal(root, null, 'a.txt')).toBe(path.join(root, 'a.txt'))
  })

  it('父目录在镜像中有 local_path → 拼接父路径', () => {
    getRemoteNode.mockReturnValue({ id: 5, local_path: '/home/u/zhyCloud/测试' })
    expect(serverPathToLocal(root, 5, 'b.txt')).toBe(path.join(root, '测试', 'b.txt'))
  })

  it('父目录缺失或无 local_path → 退化挂到根目录', () => {
    getRemoteNode.mockReturnValue(null)
    expect(serverPathToLocal(root, 99, 'c.txt')).toBe(path.join(root, 'c.txt'))

    getRemoteNode.mockReturnValue({ id: 99, local_path: null })
    expect(serverPathToLocal(root, 99, 'c.txt')).toBe(path.join(root, 'c.txt'))
  })
})

describe('localPathToServerId', () => {
  it('优先查 remote_nodes', () => {
    getRemoteNodeByPath.mockReturnValue({ id: 10 })
    getLocalState.mockReturnValue({ server_id: 20 })
    expect(localPathToServerId('/x/a.txt')).toBe(10)
    expect(getLocalState).not.toHaveBeenCalled()
  })

  it('remote_nodes 未命中时查 local_state', () => {
    getRemoteNodeByPath.mockReturnValue(null)
    getLocalState.mockReturnValue({ server_id: 20 })
    expect(localPathToServerId('/x/a.txt')).toBe(20)
  })

  it('两处都未命中 → null', () => {
    getRemoteNodeByPath.mockReturnValue(null)
    getLocalState.mockReturnValue(null)
    expect(localPathToServerId('/x/a.txt')).toBeNull()
  })

  it('local_state 存在但无 server_id → null', () => {
    getRemoteNodeByPath.mockReturnValue(null)
    getLocalState.mockReturnValue({ server_id: null })
    expect(localPathToServerId('/x/a.txt')).toBeNull()
  })
})

describe('localParentToServerId', () => {
  it('本地路径等于同步根目录 → null（对应服务端根）', () => {
    expect(localParentToServerId('/home/u/zhyCloud', '/home/u/zhyCloud')).toBeNull()
    expect(localParentToServerId('/home/u/zhyCloud', '/home/u/zhyCloud/')).toBeNull()
  })

  it('子目录 → 走 localPathToServerId 查找', () => {
    getRemoteNodeByPath.mockReturnValue({ id: 33 })
    expect(localParentToServerId('/home/u/zhyCloud', '/home/u/zhyCloud/测试')).toBe(33)
  })
})
