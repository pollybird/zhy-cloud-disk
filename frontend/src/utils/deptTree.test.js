import { describe, expect, it } from 'vitest'
import { canWrite, findDeptNode } from './deptTree'

const tree = [
  {
    id: 1,
    name: '总公司',
    my_permission: 'read_only',
    children: [
      { id: 2, name: '技术部', my_permission: 'read_write', children: [
        { id: 4, name: '前端组', my_permission: 'read_only', children: [] },
      ] },
      { id: 3, name: '行政部', my_permission: 'none', children: [] },
    ],
  },
  { id: 5, name: '分公司', my_permission: 'read_only', children: [] },
]

describe('findDeptNode', () => {
  it('命中根节点', () => {
    expect(findDeptNode(tree, 1).name).toBe('总公司')
  })

  it('深度优先命中子孙节点', () => {
    expect(findDeptNode(tree, 4).name).toBe('前端组')
    expect(findDeptNode(tree, 5).name).toBe('分公司')
  })

  it('未命中返回 null', () => {
    expect(findDeptNode(tree, 999)).toBeNull()
  })

  it('空树与空 id 安全返回 null', () => {
    expect(findDeptNode([], 1)).toBeNull()
    expect(findDeptNode(tree, null)).toBeNull()
    expect(findDeptNode(tree, undefined)).toBeNull()
    expect(findDeptNode(null, 1)).toBeNull()
  })
})

describe('canWrite', () => {
  it('仅 read_write 可写', () => {
    expect(canWrite('read_write')).toBe(true)
    expect(canWrite('read_only')).toBe(false)
    expect(canWrite('none')).toBe(false)
  })

  it('空值安全处理为不可写', () => {
    expect(canWrite(null)).toBe(false)
    expect(canWrite(undefined)).toBe(false)
    expect(canWrite('')).toBe(false)
  })
})
