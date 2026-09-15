/**
 * keystore.test.js — token 安全存储：safeStorage 加密 / 明文降级 / 解密失败兜底
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('electron', () => ({
  safeStorage: {
    isEncryptionAvailable: vi.fn(() => true),
    encryptString: vi.fn((s) => Buffer.from(`ENC[${s}]`)),
    decryptString: vi.fn((buf) => {
      const s = buf.toString('utf8')
      if (!s.startsWith('ENC[') || !s.endsWith(']')) throw new Error('corrupt')
      return s.slice(4, -1)
    }),
  },
}))

vi.mock('electron-store', () => {
  const data = new Map()
  class Store {
    get(k) {
      return data.get(k)
    }
    set(k, v) {
      data.set(k, v)
    }
    delete(k) {
      data.delete(k)
    }
  }
  return { default: Store }
})

import { safeStorage } from 'electron'
import store from '../src/lib/store/settings.js'
import { saveTokens, getAccessToken, getRefreshToken, clearTokens } from '../src/lib/store/keystore.js'

beforeEach(() => {
  vi.clearAllMocks()
  store.delete('keystore.access')
  store.delete('keystore.refresh')
  safeStorage.isEncryptionAvailable.mockReturnValue(true)
})

describe('加密可用（safeStorage）', () => {
  it('保存 → base64 密文；读取 → 解密还原', () => {
    saveTokens('access-xyz', 'refresh-abc')

    const rawAccess = store.get('keystore.access')
    expect(rawAccess).not.toBe('access-xyz') // 已加密
    expect(Buffer.from(rawAccess, 'base64').toString()).toBe('ENC[access-xyz]')

    expect(getAccessToken()).toBe('access-xyz')
    expect(getRefreshToken()).toBe('refresh-abc')
  })

  it('null token 不写入', () => {
    saveTokens('access-xyz', null)
    expect(store.get('keystore.refresh')).toBeUndefined()
    expect(getRefreshToken()).toBeNull()
  })
})

describe('加密不可用（降级明文）', () => {
  it('明文保存与读取', () => {
    safeStorage.isEncryptionAvailable.mockReturnValue(false)
    saveTokens('plain-a', 'plain-r')
    expect(store.get('keystore.access')).toBe('plain-a')
    expect(getAccessToken()).toBe('plain-a')
    expect(getRefreshToken()).toBe('plain-r')
  })
})

describe('解密失败兜底', () => {
  it('密文损坏 → 返回 null 而非抛错', () => {
    store.set('keystore.access', 'not-valid-base64-content!!')
    expect(getAccessToken()).toBeNull()
  })

  it('未存储 → 返回 null', () => {
    expect(getAccessToken()).toBeNull()
    expect(getRefreshToken()).toBeNull()
  })
})

describe('clearTokens', () => {
  it('清除后读取为 null', () => {
    saveTokens('a', 'r')
    clearTokens()
    expect(getAccessToken()).toBeNull()
    expect(getRefreshToken()).toBeNull()
  })
})
