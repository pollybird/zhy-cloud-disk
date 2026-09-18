import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/file', () => ({
  chunkInit: vi.fn(),
  instantUpload: vi.fn(),
  uploadChunk: vi.fn(),
  chunkComplete: vi.fn(),
  chunkAbort: vi.fn(),
  chunkStatus: vi.fn(),
}))

import {
  chunkComplete,
  chunkInit,
  instantUpload,
  uploadChunk,
} from '../api/file'
import {
  CHUNK_SIZE,
  pendingIndexes,
  progressFromReceived,
  shouldUseChunk,
  totalChunks,
  uploadInChunks,
} from './chunkUploader'

function fakeFile(size = CHUNK_SIZE * 4 + 123) {
  return {
    name: 'big.bin',
    size,
    slice: () => new Blob([new Uint8Array(1)]),
  }
}

function initPayload(received = []) {
  return {
    instant: false,
    upload_id: 'sid',
    total_chunks: 4,
    received,
  }
}

describe('chunkUploader 纯函数', () => {
  it('阈值：>20MB 才分片', () => {
    expect(shouldUseChunk({ size: 20 * 1024 * 1024 })).toBe(false)
    expect(shouldUseChunk({ size: 20 * 1024 * 1024 + 1 })).toBe(true)
  })

  it('totalChunks 向上取整', () => {
    expect(totalChunks(0)).toBe(0)
    expect(totalChunks(CHUNK_SIZE)).toBe(1)
    expect(totalChunks(CHUNK_SIZE + 1)).toBe(2)
  })

  it('pendingIndexes 求断点缺失分片', () => {
    expect(pendingIndexes([0, 2], 4)).toEqual([1, 3])
    expect(pendingIndexes([0, 1, 2, 3], 4)).toEqual([])
    expect(pendingIndexes(undefined, 2)).toEqual([0, 1])
  })

  it('progressFromReceived 0~99 单调', () => {
    const size = CHUNK_SIZE * 2
    expect(progressFromReceived([], 2, size)).toBe(0)
    expect(progressFromReceived([0], 2, size)).toBe(50)
    // complete 前封顶 99
    expect(progressFromReceived([0, 1], 2, size)).toBe(99)
  })
})

describe('uploadInChunks', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    chunkComplete.mockResolvedValue({ data: { node: { id: 1 } } })
  })
  afterEach(() => vi.restoreAllMocks())

  it('init 命中秒传时零分片上传', async () => {
    chunkInit.mockResolvedValue({ data: { instant: true } })
    instantUpload.mockResolvedValue({
      data: { instant: true, node: { id: 9 }, skipped: false },
    })
    const r = await uploadInChunks({ file: fakeFile(), hash: 'h' })
    expect(r.instant).toBe(true)
    expect(r.node.id).toBe(9)
    expect(uploadChunk).not.toHaveBeenCalled()
    expect(chunkComplete).not.toHaveBeenCalled()
  })

  it('断点恢复：仅上传缺失分片并 complete', async () => {
    chunkInit.mockResolvedValue({ data: initPayload([0, 2]) })
    uploadChunk.mockResolvedValue({ data: {} })
    const r = await uploadInChunks({ file: fakeFile(), hash: 'h' })

    expect(uploadChunk).toHaveBeenCalledTimes(2)
    const indexes = uploadChunk.mock.calls.map(([fd]) => fd.get('index'))
    expect(indexes.sort()).toEqual(['1', '3'])
    expect(chunkComplete).toHaveBeenCalledWith('sid')
    expect(r.node.id).toBe(1)
  })

  it('单片失败自动重试至多 3 次', async () => {
    chunkInit.mockResolvedValue({ data: initPayload([]) })
    let chunk0Attempts = 0
    uploadChunk.mockImplementation((fd) => {
      if (fd.get('index') === '0') {
        chunk0Attempts += 1
        if (chunk0Attempts < 3) return Promise.reject(new Error('network'))
      }
      return Promise.resolve({ data: {} })
    })

    await uploadInChunks({ file: fakeFile(), hash: 'h' })
    // 分片 0：2 次失败 + 1 次成功；其余各 1 次
    expect(chunk0Attempts).toBe(3)
    expect(uploadChunk).toHaveBeenCalledTimes(6)
    expect(chunkComplete).toHaveBeenCalledTimes(1)
  })

  it('取消请求抛出取消错误且不 complete', async () => {
    chunkInit.mockResolvedValue({ data: initPayload([]) })
    uploadChunk.mockRejectedValue(Object.assign(new Error('aborted'), {
      code: 'ERR_CANCELED',
    }))
    const controller = new AbortController()
    const p = uploadInChunks({
      file: fakeFile(CHUNK_SIZE + 1), hash: 'h', signal: controller.signal,
    })
    await expect(p).rejects.toThrow()
    expect(chunkComplete).not.toHaveBeenCalled()
  })
})
