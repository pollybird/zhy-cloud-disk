/**
 * hasher.test.js — MD5 计算与文件信息
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import crypto from 'crypto'
import fs from 'fs'
import os from 'os'
import path from 'path'
import { computeMd5, getFileInfo } from '../src/lib/sync/hasher.js'

let dir

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'zhy-hasher-'))
})

afterEach(() => {
  fs.rmSync(dir, { recursive: true, force: true })
})

describe('computeMd5', () => {
  it('计算内容正确的 MD5', async () => {
    const file = path.join(dir, 'a.txt')
    fs.writeFileSync(file, 'hello world')
    const md5 = await computeMd5(file)
    expect(md5).toBe(crypto.createHash('md5').update('hello world').digest('hex'))
  })

  it('空文件返回空内容 MD5', async () => {
    const file = path.join(dir, 'empty.txt')
    fs.writeFileSync(file, '')
    const md5 = await computeMd5(file)
    expect(md5).toBe('d41d8cd98f00b204e9800998ecf8427e')
  })

  it('大于分块尺寸（2MB）的文件仍计算正确', async () => {
    const file = path.join(dir, 'big.bin')
    const buf = crypto.randomBytes(5 * 1024 * 1024)
    fs.writeFileSync(file, buf)
    const md5 = await computeMd5(file)
    expect(md5).toBe(crypto.createHash('md5').update(buf).digest('hex'))
  })

  it('文件不存在时 reject', async () => {
    await expect(computeMd5(path.join(dir, 'nope.txt'))).rejects.toThrow()
  })
})

describe('getFileInfo', () => {
  it('返回正确的 size / mtime / md5', async () => {
    const file = path.join(dir, 'b.txt')
    fs.writeFileSync(file, '12345')
    const info = await getFileInfo(file)
    expect(info.size).toBe(5)
    expect(info.md5).toBe(crypto.createHash('md5').update('12345').digest('hex'))
    const stat = fs.statSync(file)
    expect(info.mtime).toBe(Math.floor(stat.mtimeMs / 1000))
  })
})
