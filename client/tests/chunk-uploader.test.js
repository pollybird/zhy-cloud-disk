/**
 * chunk-uploader.test.js — 分片编排（断点续传/重试/秒传分支）与统一上传入口
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import fs from 'fs'
import fsp from 'fs/promises'
import os from 'os'
import path from 'path'

vi.mock('../src/lib/api/file.js', () => ({
  chunkInit: vi.fn(),
  chunkComplete: vi.fn(),
  chunkAbort: vi.fn(),
  instantUpload: vi.fn(),
  uploadChunkPart: vi.fn(),
  uploadFile: vi.fn(),
}))
vi.mock('../src/lib/api/department.js', () => ({
  uploadDeptFile: vi.fn(),
}))

import {
  chunkComplete,
  chunkInit,
  instantUpload,
  uploadFile,
} from '../src/lib/api/file.js'
import { uploadDeptFile } from '../src/lib/api/department.js'
import {
  CHUNK_SIZE,
  pendingIndexes,
  uploadInChunks,
  uploadLocal,
} from '../src/lib/sync/chunk-uploader.js'

let dir

beforeEach(async () => {
  vi.clearAllMocks()
  dir = await fsp.mkdtemp(path.join(os.tmpdir(), 'zhy-chunk-'))
})
afterEach(() => {
  fs.rmSync(dir, { recursive: true, force: true })
})

async function makeTemp(name = 'f.bin', size = 10) {
  const p = path.join(dir, name)
  await fsp.writeFile(p, Buffer.alloc(size, 7))
  return p
}

function fakePartApi({ partImpl } = {}) {
  const uploadPart = vi.fn(partImpl || (async () => ({ data: {} })))
  return {
    chunkInit: vi.fn(async () => ({
      instant: false,
      upload_id: 'sid',
      total_chunks: 4,
      received: [],
    })),
    uploadPart,
    complete: vi.fn(async () => ({ node: { id: 1 } })),
    abort: vi.fn(),
    readChunk: vi.fn(async (i) => ({ buffer: Buffer.from([i]), hash: `h${i}` })),
  }
}

describe('pendingIndexes', () => {
  it('根据已收序号求缺失分片', () => {
    expect(pendingIndexes([0, 2], 4)).toEqual([1, 3])
    expect(pendingIndexes([], 2)).toEqual([0, 1])
    expect(pendingIndexes([0, 1], 2)).toEqual([])
  })
})

describe('uploadInChunks', () => {
  it('断点恢复：仅上传缺失分片，单片携带 MD5', async () => {
    const api = fakePartApi()
    api.chunkInit.mockResolvedValue({
      instant: false, upload_id: 'sid', total_chunks: 4, received: [0, 2],
    })
    const onProgress = vi.fn()
    const r = await uploadInChunks({
      filePath: '/x/f.bin', fileSize: CHUNK_SIZE * 4, fileHash: 'full',
      api, onProgress,
    })

    expect(api.uploadPart).toHaveBeenCalledTimes(2)
    const indexes = api.uploadPart.mock.calls.map((c) => c[1])
    expect(indexes.sort()).toEqual([1, 3])
    // 单片参数：uploadId, index, buffer, chunkHash, signal
    expect(api.uploadPart.mock.calls[0][0]).toBe('sid')
    expect(api.uploadPart.mock.calls[0][3]).toBe(`h${api.uploadPart.mock.calls[0][1]}`)
    expect(api.complete).toHaveBeenCalledWith('sid')
    expect(r.node).toEqual({ id: 1 })
    expect(onProgress).toHaveBeenCalledWith(100)
  })

  it('init 命中秒传：零分片直接返回节点', async () => {
    const api = fakePartApi()
    api.chunkInit.mockResolvedValue({ instant: true })
    instantUpload.mockResolvedValue({
      instant: true, node: { id: 9 }, skipped: false,
    })
    const r = await uploadInChunks({
      filePath: '/x/f.bin', fileSize: 100, fileHash: 'full', api,
    })
    expect(r).toMatchObject({ instant: true, node: { id: 9 } })
    expect(api.uploadPart).not.toHaveBeenCalled()
    expect(api.complete).not.toHaveBeenCalled()
  })

  it('单片失败重试至多 3 次', async () => {
    const api = fakePartApi()
    let attempts0 = 0
    api.uploadPart.mockImplementation(async (_sid, index) => {
      if (index === 0) {
        attempts0 += 1
        if (attempts0 < 3) throw new Error('network')
      }
      return {}
    })
    await uploadInChunks({
      filePath: '/x/f.bin', fileSize: CHUNK_SIZE * 4, fileHash: 'full', api,
    })
    expect(attempts0).toBe(3)
    expect(api.uploadPart).toHaveBeenCalledTimes(6)
    expect(api.complete).toHaveBeenCalledTimes(1)
  })

  it('取消信号中断上传且不 complete', async () => {
    const api = fakePartApi()
    const controller = new AbortController()
    api.uploadPart.mockImplementation(async () => {
      controller.abort()
      throw Object.assign(new Error('aborted'), { code: 'ERR_CANCELED' })
    })
    await expect(
      uploadInChunks({
        filePath: '/x/f.bin', fileSize: CHUNK_SIZE + 1, fileHash: 'full',
        api, signal: controller.signal,
      }),
    ).rejects.toThrow()
    expect(api.complete).not.toHaveBeenCalled()
  })
})

describe('uploadLocal 统一入口', () => {
  it('秒传命中：零流量返回 instant', async () => {
    const p = await makeTemp('a.doc')
    instantUpload.mockResolvedValue({ instant: true, node: { id: 11 }, skipped: false })
    const onProgress = vi.fn()
    const r = await uploadLocal(p, { parentId: 3, fileHash: 'hhh', onProgress })

    expect(instantUpload).toHaveBeenCalledWith(expect.objectContaining({
      parent_id: 3, file_hash: 'hhh', file_size: 10,
    }))
    expect(r).toMatchObject({ instant: true, node: { id: 11 } })
    expect(uploadFile).not.toHaveBeenCalled()
    expect(onProgress).toHaveBeenCalledWith(100)
  })

  it('秒传未命中的个人小文件走整文件上传', async () => {
    const p = await makeTemp('b.doc')
    instantUpload.mockResolvedValue({ instant: false })
    uploadFile.mockResolvedValue({ success: [{ id: 12 }] })
    const r = await uploadLocal(p, { parentId: null, fileHash: 'hhh' })
    expect(uploadFile).toHaveBeenCalledWith(p, null, 'hhh', 'normal')
    expect(r.node.id).toBe(12)
  })

  it('部门文件秒传未命中走部门上传通道', async () => {
    const p = await makeTemp('c.doc')
    instantUpload.mockResolvedValue({ instant: false })
    uploadDeptFile.mockResolvedValue({ success: [{ id: 13 }] })
    const r = await uploadLocal(p, { departmentId: 5, parentId: 2, fileHash: 'hhh' })
    expect(uploadDeptFile).toHaveBeenCalledWith(
      p, expect.objectContaining({ departmentId: 5, parentId: 2 }),
    )
    expect(r.node.id).toBe(13)
  })

  it('overwrite 模式直接整文件覆盖并带 overwriteId', async () => {
    const p = await makeTemp('d.doc')
    uploadDeptFile.mockResolvedValue({ success: [{ id: 14 }] })
    const r = await uploadLocal(p, {
      departmentId: 5, mode: 'overwrite', overwriteId: 8, fileHash: 'hhh',
    })
    expect(instantUpload).not.toHaveBeenCalled()
    expect(uploadDeptFile).toHaveBeenCalledWith(
      p, expect.objectContaining({ mode: 'overwrite', overwriteId: 8 }),
    )
    expect(r).toMatchObject({ instant: false, node: { id: 14 } })
  })

  it('大文件（>20MB）秒传未命中走分片通道', async () => {
    const p = path.join(dir, 'big.bin')
    const fh = await fsp.open(p, 'w')
    await fh.truncate(CHUNK_SIZE * 4 + 1)
    await fh.close()
    instantUpload.mockResolvedValue({ instant: false })
    const chunks = vi.fn(async () => ({ node: { id: 15 }, instant: false }))
    const r = await uploadLocal(p, { fileHash: 'hhh', chunks })
    expect(chunks).toHaveBeenCalledWith(expect.objectContaining({
      fileSize: CHUNK_SIZE * 4 + 1, fileHash: 'hhh',
    }))
    expect(r.node.id).toBe(15)
    expect(uploadFile).not.toHaveBeenCalled()
  })

  it('秒传接口异常时静默降级为普通上传', async () => {
    const p = await makeTemp('e.doc')
    instantUpload.mockRejectedValue(new Error('500'))
    chunkComplete.mockResolvedValue({ node: { id: 16 } })
    uploadFile.mockResolvedValue({ success: [{ id: 16 }] })
    const r = await uploadLocal(p, { fileHash: 'hhh' })
    expect(r.node.id).toBe(16)
  })
})
