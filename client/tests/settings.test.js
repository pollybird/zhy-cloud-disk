/**
 * settings.test.js — 设置持久化（electron-store mock）
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('electron-store', () => {
  const data = new Map()
  class Store {
    constructor(opts = {}) {
      Object.entries(opts.defaults || {}).forEach(([k, v]) => {
        if (!data.has(k)) data.set(k, v)
      })
    }
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

import store, {
  getSettings,
  setSetting,
  setSettings,
  isConfigured,
  resetSettings,
} from '../src/lib/store/settings.js'

const DEFAULTS = {
  serverUrl: '',
  username: '',
  syncPath: '',
  autoStart: false,
  pollInterval: 60,
  conflictStrategy: 'keep-both',
  configured: false,
}

beforeEach(() => {
  Object.entries(DEFAULTS).forEach(([k, v]) => store.set(k, v))
})

describe('默认值', () => {
  it('getSettings 返回全部默认配置', () => {
    expect(getSettings()).toEqual(DEFAULTS)
  })
})

describe('读写', () => {
  it('setSetting 单键写入', () => {
    setSetting('pollInterval', 120)
    expect(store.get('pollInterval')).toBe(120)
  })

  it('setSettings 批量合并', () => {
    setSettings({ serverUrl: 'http://s', username: 'u', configured: true })
    expect(getSettings()).toMatchObject({
      serverUrl: 'http://s',
      username: 'u',
      configured: true,
      pollInterval: 60, // 未触及的键保持不变
    })
  })
})

describe('isConfigured', () => {
  it('configured + serverUrl + syncPath 齐备 → true', () => {
    setSettings({ configured: true, serverUrl: 'http://s', syncPath: '/p' })
    expect(isConfigured()).toBe(true)
  })

  it('缺任一项 → false', () => {
    setSettings({ configured: true, serverUrl: 'http://s', syncPath: '' })
    expect(isConfigured()).toBe(false)

    setSettings({ configured: false, syncPath: '/p' })
    expect(isConfigured()).toBe(false)
  })
})

describe('resetSettings', () => {
  it('清空账号相关配置，configured 置 false', () => {
    setSettings({ configured: true, serverUrl: 'http://s', username: 'u', syncPath: '/p' })
    resetSettings()
    expect(getSettings()).toMatchObject({
      configured: false,
      serverUrl: '',
      username: '',
      syncPath: '',
    })
  })
})
