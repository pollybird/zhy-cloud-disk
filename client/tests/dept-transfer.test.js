/**
 * dept-transfer.test.js — 上传查重编排 / 冲突决策执行 / 文件夹递归下载
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('fs/promises', () => ({
  default: {
    mkdir: vi.fn().mockResolvedValue(undefined),
    unlink: vi.fn().mockRejectedValue(Object.assign(new Error('ENOENT'), { code: 'ENOENT' })),
  },
}))

import fsp from 'fs/promises'
import {
  sanitizeName,
  planUploads,
  executeUploads,
  downloadItems,
} from '../src/lib/dept/dept-transfer.js'

beforeEach(() => {
  vi.clearAllMocks()
  fsp.mkdir.mockResolvedValue(undefined)
  fsp.unlink.mockRejectedValue(Object.assign(new Error('ENOENT'), { code: 'ENOENT' }))
})

describe('sanitizeName', () => {
  it('替换 Windows 非法字符', () => {
    expect(sanitizeName('a/b:c*d?.txt')).toBe('a_b_c_d_.txt')
  })
})

describe('planUploads', () => {
  it('stat + md5 + 查重，映射服务端 action', async () => {
    const stat = vi.fn(async () => ({ isFile: () => true, size: 10 }))
    const md5 = vi.fn(async (p) => `hash-${p}`)
    const check = vi.fn(async ({ fileName }) => ({
      action: fileName === 'same.doc' ? 'skip' : fileName === 'new.doc' ? 'upload' : 'conflict',
      existing: fileName === 'diff.doc' ? { id: 88 } : null,
    }))
    const plans = await planUploads(['/tmp/same.doc', '/tmp/new.doc', '/tmp/diff.doc'], {
      departmentId: 2,
      parentId: 5,
      stat,
      md5,
      check,
    })
    expect(plans.map((p) => [p.fileName, p.action])).toEqual([
      ['same.doc', 'skip'],
      ['new.doc', 'upload'],
      ['diff.doc', 'conflict'],
    ])
    expect(plans[2].existing).toEqual({ id: 88 })
    expect(check).toHaveBeenCalledWith(
      expect.objectContaining({ departmentId: 2, parentId: 5 })
    )
  })

  it('非文件跳过；异常落为 error 计划', async () => {
    const stat = vi.fn(async (p) =>
      p === '/tmp/dir'
        ? { isFile: () => false }
        : Promise.reject(new Error('boom'))
    )
    const plans = await planUploads(['/tmp/dir', '/tmp/bad.doc'], {
      departmentId: 1,
      stat,
      md5: vi.fn(),
      check: vi.fn(),
    })
    expect(plans).toHaveLength(1)
    expect(plans[0]).toMatchObject({ fileName: 'bad.doc', action: 'error', error: 'boom' })
  })
})

describe('executeUploads', () => {
  it('skip/error 不上传；upload 普通模式；conflict 按决策覆盖并带 overwriteId', async () => {
    const plans = [
      { path: '/s', fileName: 's', fileHash: 'hs', action: 'skip' },
      { path: '/e', fileName: 'e', action: 'error', error: 'x' },
      { path: '/n', fileName: 'n', fileHash: 'hn', action: 'upload' },
      { path: '/c', fileName: 'c', fileHash: 'hc', action: 'conflict', existing: { id: 9 } },
      { path: '/c2', fileName: 'c2', fileHash: 'hc2', action: 'conflict', existing: { id: 10 } },
    ]
    const upload = vi.fn(async (filePath, payload) => ({ success: [{ id: 1, file_name: filePath }] }))
    const onProgress = vi.fn()

    const res = await executeUploads(plans, {
      departmentId: 4,
      parentId: 6,
      overwrite: true,
      upload,
      onProgress,
    })

    expect(upload).toHaveBeenCalledTimes(3)
    expect(upload).toHaveBeenCalledWith(
      '/n',
      expect.objectContaining({ departmentId: 4, parentId: 6, fileHash: 'hn', onProgress: expect.any(Function) })
    )
    const overwritePayload = upload.mock.calls[1][1]
    expect(overwritePayload).toMatchObject({ mode: 'overwrite', overwriteId: 9 })
    expect(res.success).toHaveLength(3)
    expect(res.skipped).toHaveLength(2)
    expect(res.failed).toEqual([])
    expect(onProgress).toHaveBeenCalled()
  })

  it('overwrite=false 时冲突文件跳过', async () => {
    const upload = vi.fn(async () => ({ success: [{}] }))
    const res = await executeUploads(
      [{ path: '/c', fileName: 'c', action: 'conflict', existing: { id: 1 } }],
      { departmentId: 1, overwrite: false, upload }
    )
    expect(upload).not.toHaveBeenCalled()
    expect(res.skipped).toHaveLength(1)
  })

  it('单个上传失败计入 failed 且不中断后续', async () => {
    const upload = vi
      .fn()
      .mockRejectedValueOnce(new Error('网络中断'))
      .mockResolvedValueOnce({ success: [{}] })
    const res = await executeUploads(
      [
        { path: '/a', fileName: 'a', action: 'upload' },
        { path: '/b', fileName: 'b', action: 'upload' },
      ],
      { departmentId: 1, upload }
    )
    expect(res.failed).toHaveLength(1)
    expect(res.failed[0].message).toBe('网络中断')
    expect(res.success).toHaveLength(1)
  })
})

describe('downloadItems', () => {
  function makeListFiles() {
    return vi.fn(async ({ parentId, page }) => {
      if (parentId === 2) {
        // docs：先子文件夹 sub 后文件 b.txt（服务端文件夹优先排序）
        return {
          items: [
            { id: 4, file_name: 'sub', is_folder: true, department_id: 5 },
            { id: 3, file_name: 'b.txt', is_folder: false, department_id: 5 },
          ],
          total: 2,
        }
      }
      if (parentId === 4) {
        return {
          items: [{ id: 5, file_name: 'c.txt', is_folder: false, department_id: 5 }],
          total: 1,
        }
      }
      // 大目录分页：总数 250
      const start = (page - 1) * 200
      const count = page === 1 ? 200 : 50
      return {
        items: Array.from({ length: count }, (_v, i) => ({
          id: 1000 + start + i,
          file_name: `f${start + i}.bin`,
          is_folder: false,
          department_id: 5,
        })),
        total: 250,
      }
    })
  }

  it('递归下载文件与文件夹，保留目录结构，非法名清洗', async () => {
    const listFiles = makeListFiles()
    const download = vi.fn(async () => undefined)
    const onProgress = vi.fn()
    const nodes = [
      { id: 1, file_name: 'a.txt', is_folder: false, department_id: 5 },
      { id: 2, file_name: 'docs', is_folder: true, department_id: 5 },
    ]
    const res = await downloadItems(nodes, '/target', { listFiles, download, onProgress })

    expect(res.success).toBe(3)
    expect(res.failed).toEqual([])
    // 按选中节点顺序：顶层文件先入列，再递归文件夹（sub/c.txt、b.txt）
    expect(download.mock.calls.map((c) => c[0])).toEqual([1, 5, 3])
    expect(download.mock.calls[0][1].replaceAll('\\', '/')).toBe('/target/a.txt')
    expect(download.mock.calls[1][1].replaceAll('\\', '/')).toBe('/target/docs/sub/c.txt')
    expect(download.mock.calls[2][1].replaceAll('\\', '/')).toBe('/target/docs/b.txt')
    expect(fsp.mkdir).toHaveBeenCalled()
    // 进度上报
    expect(onProgress).toHaveBeenLastCalledWith(
      expect.objectContaining({ phase: 'download', current: 3, total: 3 })
    )
  })

  it('分页拉取超过 200 项的大文件夹', async () => {
    const listFiles = makeListFiles()
    const download = vi.fn(async () => undefined)
    const nodes = [{ id: 20, file_name: 'big', is_folder: true, department_id: 5 }]
    // big 目录的 parentId=20 走分页分支
    const res = await downloadItems(nodes, '/t', { listFiles, download })
    expect(res.success).toBe(250)
    expect(listFiles).toHaveBeenCalledWith(
      expect.objectContaining({ parentId: 20, page: 1, size: 200 })
    )
    expect(listFiles).toHaveBeenCalledWith(
      expect.objectContaining({ parentId: 20, page: 2, size: 200 })
    )
  })

  it('已存在的目标文件先删除；单文件失败不阻断整体', async () => {
    fsp.unlink.mockReset()
    fsp.unlink.mockResolvedValue(undefined)
    const listFiles = vi.fn(async () => ({ items: [], total: 0 }))
    const download = vi
      .fn()
      .mockRejectedValueOnce(new Error('磁盘满'))
      .mockResolvedValueOnce(undefined)
    const nodes = [
      { id: 1, file_name: 'x.txt', is_folder: false, department_id: 5 },
      { id: 2, file_name: 'y.txt', is_folder: false, department_id: 5 },
    ]
    const res = await downloadItems(nodes, '/t', { listFiles, download })
    expect(res.success).toBe(1)
    expect(res.failed).toEqual([{ name: 'x.txt', message: '磁盘满' }])
    expect(fsp.unlink).toHaveBeenCalledTimes(2)
  })
})
