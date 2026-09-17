/**
 * dept-upload-tree.test.js — 按本地目录结构上传的编排
 */
import { describe, it, expect, vi } from 'vitest'
import { uploadGroupsToDept } from '../src/lib/dept/upload-tree.js'

function makeCtx(overwriteAnswer) {
  const listFolders = vi.fn(async (parent) => {
    if (parent === null) return [{ id: 100, file_name: 'proj' }]
    if (parent === 100) return [{ id: 101, file_name: 'sub' }]
    return []
  })
  const createFolder = vi.fn(async (parent, name) => ({ id: 999, file_name: name }))
  const plan = vi.fn(async (paths) =>
    paths.map((p) => {
      const base = p.split(/[\\/]/).pop()
      const action = base === 'conflict.doc' ? 'conflict' : 'upload'
      return {
        path: p,
        fileName: base,
        action,
        existing: action === 'conflict' ? { id: 55 } : null,
      }
    })
  )
  const upload = vi.fn(async (plans, _parent, overwrite) => {
    const doing = plans.filter((p) => !(p.action === 'conflict' && !overwrite))
    return {
      success: doing.map((p) => ({ plan: p })),
      skipped: plans.filter((p) => p.action === 'conflict' && !overwrite),
      failed: [],
    }
  })
  const askOverwrite = vi.fn(async () => overwriteAnswer)
  return { listFolders, createFolder, plan, upload, askOverwrite }
}

describe('uploadGroupsToDept', () => {
  it('散文件直传当前目录；拖入目录在远端重建结构（已存在文件夹复用，不重复创建）', async () => {
    const ctx = makeCtx(false)
    const groups = [
      { rootName: null, files: ['/tmp/flat.doc'] },
      {
        rootName: 'proj',
        files: ['/d/proj/top.doc', '/d/proj/sub/deep.doc'],
      },
    ]
    const res = await uploadGroupsToDept(groups, {
      departmentId: 3,
      parentId: null,
      ...ctx,
    })

    // proj 在根目录已存在（id=100）→ 不创建；sub 也已存在（id=101）→ 不创建
    expect(ctx.createFolder).not.toHaveBeenCalled()

    // 三个目标桶：根散文件 / proj 根 / proj/sub
    expect(ctx.plan).toHaveBeenCalledTimes(3)
    expect(ctx.plan).toHaveBeenNthCalledWith(1, ['/tmp/flat.doc'], null)
    expect(ctx.plan).toHaveBeenNthCalledWith(2, ['/d/proj/top.doc'], 100)
    expect(ctx.plan).toHaveBeenNthCalledWith(3, ['/d/proj/sub/deep.doc'], 101)

    // 无冲突 → 不询问；全部上传成功
    expect(ctx.askOverwrite).not.toHaveBeenCalled()
    expect(res.success).toBe(3)
    expect(res.skipped).toBe(0)
    expect(res.failed).toEqual([])
  })

  it('缺失的目录层级按需创建', async () => {
    const ctx = makeCtx(false)
    ctx.listFolders.mockImplementation(async () => []) // 所有层级都不存在
    let fid = 1000
    ctx.createFolder.mockImplementation(async (parent, name) => ({ id: ++fid, file_name: name }))
    const groups = [{ rootName: 'newdir', files: ['/d/newdir/a/b/x.txt'] }]
    const res = await uploadGroupsToDept(groups, { departmentId: 1, parentId: 7, ...ctx })

    expect(ctx.createFolder).toHaveBeenCalledTimes(3)
    expect(ctx.createFolder).toHaveBeenNthCalledWith(1, 7, 'newdir')
    expect(ctx.createFolder).toHaveBeenNthCalledWith(2, 1001, 'a')
    expect(ctx.createFolder).toHaveBeenNthCalledWith(3, 1002, 'b')
    expect(ctx.plan).toHaveBeenCalledWith(['/d/newdir/a/b/x.txt'], 1003)
    expect(res.success).toBe(1)
  })

  it('冲突时询问一次；选择跳过 → 冲突文件计入 skipped', async () => {
    const ctx = makeCtx(false)
    const groups = [
      { rootName: null, files: ['/tmp/ok.doc', '/tmp/conflict.doc'] },
      { rootName: 'proj', files: ['/d/proj/conflict.doc'] },
    ]
    const res = await uploadGroupsToDept(groups, { departmentId: 3, parentId: null, ...ctx })

    expect(ctx.askOverwrite).toHaveBeenCalledTimes(1)
    expect(ctx.askOverwrite).toHaveBeenCalledWith(2)
    // 跳过决策透传到每个桶的 upload 调用
    expect(ctx.upload).toHaveBeenCalledWith(
      expect.any(Array),
      null,
      false
    )
    expect(res.success).toBe(1)
    expect(res.skipped).toBe(2)
  })

  it('冲突选择覆盖 → upload 收到 overwrite=true，冲突文件成功上传', async () => {
    const ctx = makeCtx(true)
    const groups = [{ rootName: null, files: ['/tmp/conflict.doc'] }]
    const res = await uploadGroupsToDept(groups, { departmentId: 3, parentId: null, ...ctx })

    expect(ctx.upload).toHaveBeenCalledWith(expect.any(Array), null, true)
    expect(res.success).toBe(1)
    expect(res.skipped).toBe(0)
  })

  it('空分组 → 不上传不询问', async () => {
    const ctx = makeCtx(true)
    const res = await uploadGroupsToDept([], { departmentId: 1, parentId: null, ...ctx })
    expect(res).toEqual({ success: 0, skipped: 0, failed: [], conflict: 0 })
    expect(ctx.plan).not.toHaveBeenCalled()
  })
})
