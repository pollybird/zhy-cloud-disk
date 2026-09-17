/**
 * dept-dragdrop.test.js — 拖拽路径收集（渲染层纯逻辑）
 */
import { describe, it, expect } from 'vitest'
import {
  splitSegments,
  isAncestorOrEqual,
  dedupeNested,
  collectDroppedPaths,
  gatherUploadFiles,
  collectDropEntries,
} from '../src/lib/dept/drag-drop.js'

describe('splitSegments', () => {
  it('兼容 POSIX 与 Windows 盘符路径，忽略空段', () => {
    expect(splitSegments('/home/u/a.txt')).toEqual(['home', 'u', 'a.txt'])
    expect(splitSegments('C:\\Users\\u\\a.txt')).toEqual(['C:', 'Users', 'u', 'a.txt'])
  })
})

describe('isAncestorOrEqual', () => {
  it('父目录为祖先', () => {
    expect(isAncestorOrEqual('/a', '/a/b/c.txt')).toBe(true)
    expect(isAncestorOrEqual('C:\\A', 'C:\\a\\b')).toBe(true) // 大小写不敏感
  })
  it('自身', () => {
    expect(isAncestorOrEqual('/a/b', '/a/b')).toBe(true)
  })
  it('非祖先', () => {
    expect(isAncestorOrEqual('/a/b', '/a/c')).toBe(false)
    expect(isAncestorOrEqual('/ab', '/a/ab')).toBe(false) // 前缀但非路径层级
  })
})

describe('dedupeNested', () => {
  it('丢弃被祖先目录覆盖的子路径', () => {
    const out = dedupeNested(['/a', '/a/b.txt', '/c/d.txt', '/c'])
    expect(out.sort()).toEqual(['/a', '/c'])
  })
  it('无包含关系时保持原样', () => {
    expect(dedupeNested(['/a/x', '/b/y']).sort()).toEqual(['/a/x', '/b/y'])
  })
})

describe('collectDroppedPaths', () => {
  it('通过 getPathForFile 取路径并去嵌套', () => {
    const files = [{ name: 'a' }, { name: 'b' }]
    const map = new Map(files.map((f) => [f, `/tmp/${f.name}.txt`]))
    const out = collectDroppedPaths(files, (f) => map.get(f))
    expect(out.sort()).toEqual(['/tmp/a.txt', '/tmp/b.txt'])
  })
  it('空拖入', () => {
    expect(collectDroppedPaths([], () => '/x')).toEqual([])
    expect(collectDroppedPaths(null, () => '/x')).toEqual([])
  })
})

describe('gatherUploadFiles', () => {
  it('文件直传、目录递归展开后合并去嵌套', async () => {
    const dataTransfer = { files: [{ name: 'f1' }, { name: 'dir' }] }
    const deps = {
      getPathForFile: (f) => (f.name === 'f1' ? '/tmp/f1.txt' : '/tmp/dir'),
      statPaths: async (paths) => ({
        files: paths.filter((p) => p === '/tmp/f1.txt'),
        dirs: paths.filter((p) => p === '/tmp/dir'),
      }),
      walkDir: async () => ['/tmp/dir/a.doc', '/tmp/dir/sub/b.doc'],
    }
    const out = await gatherUploadFiles(dataTransfer, deps)
    expect(out.sort()).toEqual(['/tmp/dir/a.doc', '/tmp/dir/sub/b.doc', '/tmp/f1.txt'])
  })
  it('空拖入不调用主进程', async () => {
    let called = false
    const out = await gatherUploadFiles(
      { files: [] },
      {
        getPathForFile: () => null,
        statPaths: async () => {
          called = true
          return { files: [], dirs: [] }
        },
        walkDir: async () => [],
      }
    )
    expect(out).toEqual([])
    expect(called).toBe(false)
  })
})

describe('collectDropEntries', () => {
  it('散文件为 null 组，拖入目录各自成组并带根名', async () => {
    const dataTransfer = { files: [{}, {}, {}] }
    const paths = ['/tmp/flat.txt', '/tmp/projA', '/tmp/projB']
    const deps = {
      getPathForFile: () => paths.shift(),
      statPaths: async (ps) => ({
        files: ps.filter((p) => p === '/tmp/flat.txt'),
        dirs: ps.filter((p) => p !== '/tmp/flat.txt'),
      }),
      walkDir: async (d) => (d === '/tmp/projA' ? ['/tmp/projA/a.md'] : ['/tmp/projB/b.md', '/tmp/projB/sub/c.md']),
    }
    const groups = await collectDropEntries(dataTransfer, deps)
    expect(groups).toHaveLength(3)
    expect(groups[0]).toEqual({ rootName: null, files: ['/tmp/flat.txt'] })
    expect(groups.find((g) => g.rootName === 'projA').files).toEqual(['/tmp/projA/a.md'])
    const b = groups.find((g) => g.rootName === 'projB')
    expect(b.files).toEqual(['/tmp/projB/b.md', '/tmp/projB/sub/c.md'])
  })
})
