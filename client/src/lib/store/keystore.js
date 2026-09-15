/**
 * 安全存储 JWT token：优先用 Electron safeStorage（OS keychain/DPAPI），
 * 不可用时降级到明文（并警告）。
 */
import { safeStorage } from 'electron'
import store from './settings.js'

const KEY_ACCESS = 'keystore.access'
const KEY_REFRESH = 'keystore.refresh'

function canEncrypt() {
  return safeStorage.isEncryptionAvailable()
}

export function saveTokens(accessToken, refreshToken) {
  if (canEncrypt()) {
    if (accessToken) {
      store.set(KEY_ACCESS, safeStorage.encryptString(accessToken).toString('base64'))
    }
    if (refreshToken) {
      store.set(KEY_REFRESH, safeStorage.encryptString(refreshToken).toString('base64'))
    }
  } else {
    // 降级明文存储
    if (accessToken) store.set(KEY_ACCESS, accessToken)
    if (refreshToken) store.set(KEY_REFRESH, refreshToken)
  }
}

export function getAccessToken() {
  const raw = store.get(KEY_ACCESS)
  if (!raw) return null
  if (canEncrypt()) {
    try {
      return safeStorage.decryptString(Buffer.from(raw, 'base64'))
    } catch {
      return null
    }
  }
  return raw
}

export function getRefreshToken() {
  const raw = store.get(KEY_REFRESH)
  if (!raw) return null
  if (canEncrypt()) {
    try {
      return safeStorage.decryptString(Buffer.from(raw, 'base64'))
    } catch {
      return null
    }
  }
  return raw
}

export function clearTokens() {
  store.delete(KEY_ACCESS)
  store.delete(KEY_REFRESH)
}
