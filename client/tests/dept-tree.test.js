/**
 * dept-tree.test.js — 部门树纯函数
 */
import { describe, it, expect } from 'vitest'
import {
  findDeptNode,
  canWrite,
  firstReadableId,
  permLabel,
  permTagType,
} from '../src/lib/dept/dept-tree.js'

const tree = [
  {
    id: 1,
    name: '总公司',
    my_permission: 'read_write',
    children: [
      { id: 2, name: '研发部', my_permission: 'read_only', children: [] },
      {
        id: 3,
        name: '市场部',
        my_permission: 'none',
        children: [{ id: 4, name: '华东组', my_permission: 'read_only', children: [] }],
      },
    ],
  },
  { id: 5, name: '独立部门', my_permission: 'read_only', children: [] },
]

describe('findDeptNode', () => {
  it('顶层命中', () => {
    expect(findDeptNode(tree, 1)?.name).toBe('总公司')
  })
  it('深层命中', () => {
    expect(findDeptNode(tree, 4)?.name).toBe('华东组')
  })
  it('未命中返回 null', () => {
    expect(findDeptNode(tree, 999)).toBeNull()
  })
  it('非法入参兜底', () => {
    expect(findDeptNode(null, 1)).toBeNull()
    expect(findDeptNode(tree, null)).toBeNull()
    expect(findDeptNode(tree, undefined)).toBeNull()
  })
})

describe('canWrite', () => {
  it('只有 read_write 为真', () => {
    expect(canWrite('read_write')).toBe(true)
    expect(canWrite('read_only')).toBe(false)
    expect(canWrite('none')).toBe(false)
    expect(canWrite(undefined)).toBe(false)
    expect(canWrite(null)).toBe(false)
  })
})

describe('firstReadableId', () => {
  it('返回第一个非 none 的部门（顶层优先，父节点先于子节点）', () => {
    expect(firstReadableId(tree)).toBe(1)
  })
  it('跳过 none 父节点但命中其可访问子节点', () => {
    expect(firstReadableId([{ id: 9, my_permission: 'none', children: tree[0].children[1].children }])).toBe(4)
  })
  it('全部无权 → null', () => {
    expect(firstReadableId([{ id: 9, my_permission: 'none', children: [] }])).toBeNull()
    expect(firstReadableId([])).toBeNull()
  })
})

describe('权限标签', () => {
  it('permLabel', () => {
    expect(permLabel('read_write')).toBe('读写')
    expect(permLabel('read_only')).toBe('只读')
    expect(permLabel('none')).toBe('无权')
  })
  it('permTagType', () => {
    expect(permTagType('read_write')).toBe('success')
    expect(permTagType('read_only')).toBe('info')
    expect(permTagType('none')).toBe('danger')
  })
})
