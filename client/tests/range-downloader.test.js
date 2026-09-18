/**
 * range-downloader.test.js — HTTP Range 断点续传 / 完整性校验
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import fs from 'fs'
import fsp from 'fs/promises'
import os from 'os'
import path from 'path'
import crypto from 'crypto'
import { Readable } from 'stream'

vi.mock('../src/lib/api/client.js', () => ({
  default: { get: vi.fn(), interceptors: { request: { use: () => {} }, response: { use: () => {} } } },
}))

import http from '../src/lib/api/client.js'
import { downloadResumable } from '../src/lib/sync/range-downloader.js'

let dir

beforeEach(async () => {
  vi.clearAllMocks()
  dir = await fsp.mkdtemp(path.join(os.tmpdir(), 'zhy-range-'))
})
afterEach(() => {
  fs.rmSync(dir, { recursive: true, force: true })
})

function streamResponse(status, headers, buffer) {
  return Promise.resolve({
    status,
    headers,
    data: Readable.from([buffer]),
  })
}

const md5 = (s) => crypto.createHash('md5').update(s).digest('hex')

describe('downloadResumable', () => {
  it('全新下载（200）落盘并清理临时元数据', async () => {
    const target = path.join(dir, 'a.txt')
    const body = Buffer.from('hello world')
    http.get.mockImplementation((url, cfg) => {
      expect(cfg.headers).toEqual({})
      return streamResponse(200, { 'content-length': String(body.length) }, body)
    })

    await downloadResumable(1, target, { expectedSize: body.length })

    expect(await fsp.readFile(target, 'utf8')).toBe('hello world')
    await expect(fsp.stat(`${target}.zhy.part`)).rejects.toThrow()
    await expect(fsp.readFile(`${target}.zhy.part.meta`, 'utf8')).rejects.toThrow()
  })

  it('临时文件身份匹配时带 Range 续传（206 追加）', async () => {
    const target = path.join(dir, 'b.txt')
    const tmp = `${target}.zhy.part`
    await fsp.writeFile(tmp, 'hello')
    await fsp.writeFile(`${tmp}.meta`, '1:11')

    http.get.mockImplementation((url, cfg) => {
      // 必须携带断点
      expect(cfg.headers.Range).toBe('bytes=5-')
      return streamResponse(
        206,
        { 'content-range': 'bytes 5-10/11', 'content-length': '6' },
        Buffer.from(' world'),
      )
    })

    await downloadResumable(1, target, { expectedSize: 11, expectedHash: md5('hello world') })
    expect(await fsp.readFile(target, 'utf8')).toBe('hello world')
  })

  it('临时文件属于其他文件（meta 不符）时丢弃并重新整下', async () => {
    const target = path.join(dir, 'c.txt')
    const tmp = `${target}.zhy.part`
    await fsp.writeFile(tmp, 'STALE')
    await fsp.writeFile(`${tmp}.meta`, '999:11')

    http.get.mockImplementation((url, cfg) => {
      expect(cfg.headers).toEqual({})
      return streamResponse(200, { 'content-length': '11' }, Buffer.from('hello world'))
    })

    await downloadResumable(1, target, { expectedSize: 11 })
    expect(await fsp.readFile(target, 'utf8')).toBe('hello world')
  })

  it('临时文件已满（等于期望大小）时也重新下载，避免拼接污染', async () => {
    const target = path.join(dir, 'd.txt')
    const tmp = `${target}.zhy.part`
    await fsp.writeFile(tmp, 'hello world')
    await fsp.writeFile(`${tmp}.meta`, '1:11')

    http.get.mockImplementation((url, cfg) => {
      expect(cfg.headers).toEqual({})
      return streamResponse(200, { 'content-length': '11' }, Buffer.from('hello world'))
    })

    await downloadResumable(1, target, { expectedSize: 11 })
    expect(http.get).toHaveBeenCalledTimes(1)
  })

  it('完成大小与期望不符时抛错并保留临时文件供重试', async () => {
    const target = path.join(dir, 'e.txt')
    http.get.mockImplementation(() =>
      streamResponse(200, { 'content-length': '5' }, Buffer.from('hello')))

    await expect(
      downloadResumable(1, target, { expectedSize: 99 }),
    ).rejects.toThrow(/大小不符/)
    expect(await fsp.readFile(`${target}.zhy.part`, 'utf8')).toBe('hello')
    await expect(fsp.stat(target)).rejects.toThrow()
  })

  it('MD5 校验失败时抛错', async () => {
    const target = path.join(dir, 'f.txt')
    http.get.mockImplementation(() =>
      streamResponse(200, { 'content-length': '11' }, Buffer.from('hello world')))

    await expect(
      downloadResumable(1, target, { expectedSize: 11, expectedHash: 'deadbeef' }),
    ).rejects.toThrow(/指纹校验失败/)
  })

  it('进度回调随下载字节递增', async () => {
    const target = path.join(dir, 'g.txt')
    const body = Buffer.from('abcdef')
    http.get.mockImplementation(() =>
      streamResponse(200, { 'content-length': '6' }, body))
    const onProgress = vi.fn()

    await downloadResumable(1, target, { expectedSize: 6, onProgress })
    expect(onProgress).toHaveBeenCalled()
    const totals = onProgress.mock.calls.map((c) => c[1])
    expect(totals.every((t) => t === 6)).toBe(true)
    const received = onProgress.mock.calls.map((c) => c[0])
    expect(received[received.length - 1]).toBe(6)
  })
})
