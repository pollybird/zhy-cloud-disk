/**
 * IPC 通道注册：renderer ↔ main 通信。
 */
import { ipcMain, dialog, shell } from 'electron'
import { getSettings, setSettings, resetSettings } from '../lib/store/settings.js'
import { saveTokens, clearTokens } from '../lib/store/keystore.js'
import { login, testConnection, logout } from '../lib/api/auth.js'
import { setCredentials, setOnAuthExpired } from '../lib/api/client.js'
import { start, stop, pause, resume, getState } from '../lib/sync/engine.js'
import { remotePoller } from '../lib/sync/remote-poller.js'
import {
  getSyncLogs,
  clearSyncLog,
} from '../lib/mirror/mirror-db.js'
import { emit, on, EVENTS } from '../lib/events.js'
import { setAutoStart, isAutoStartEnabled } from './autostart.js'
import { getMainWindow } from './window.js'
import { registerDeptIpc } from './dept-ipc.js'
import { registerHistoryIpc } from './history-ipc.js'
import { error } from '../lib/logger.js'

export function registerIpc() {
  // 部门网盘（在线浏览）通道
  registerDeptIpc()
  // 回收站与历史版本通道（1.3.0）
  registerHistoryIpc()

  // 引擎事件转发到渲染层（状态 / 进度 / 同步日志）
  on(EVENTS.STATE_CHANGE, (s) => getMainWindow()?.webContents?.send('sync:state', s))
  on(EVENTS.PROGRESS, (p) => getMainWindow()?.webContents?.send('sync:progress', p))
  on(EVENTS.LOG, (l) => getMainWindow()?.webContents?.send('sync:log', l))
  on(EVENTS.AUTH_EXPIRED, () => getMainWindow()?.webContents?.send('sync:auth-expired', true))

  // ---- 设置 ----
  ipcMain.handle('settings:get', () => getSettings())
  ipcMain.handle('settings:set', (_e, updates) => {
    setSettings(updates)
    return getSettings()
  })

  // ---- 目录选择器 ----
  ipcMain.handle('dialog:chooseFolder', async () => {
    const result = await dialog.showOpenDialog({
      properties: ['openDirectory', 'createDirectory'],
    })
    if (result.canceled || result.filePaths.length === 0) return null
    return result.filePaths[0]
  })

  // ---- 认证 ----
  ipcMain.handle('auth:login', async (_e, { serverUrl, username, password }) => {
    try {
      const { access_token, refresh_token, user } = await login(serverUrl, username, password)
      saveTokens(access_token, refresh_token)
      setCredentials(serverUrl, access_token, refresh_token)
      setSettings({ serverUrl, username, configured: true })
      return { success: true, user }
    } catch (e) {
      error(`Login failed: ${e.message}`)
      return { success: false, error: e.message }
    }
  })

  ipcMain.handle('auth:testConnection', async (_e, serverUrl) => {
    try {
      const res = await testConnection(serverUrl)
      return { success: true, data: res.data }
    } catch (e) {
      return { success: false, error: e.message }
    }
  })

  ipcMain.handle('auth:logout', async () => {
    logout()
    clearTokens()
    stop()
    resetSettings()
    return true
  })

  // ---- 同步控制 ----
  ipcMain.handle('sync:start', async () => {
    try {
      setOnAuthExpired(() => emit(EVENTS.AUTH_EXPIRED))
      await start()
      return { success: true }
    } catch (e) {
      error(`Sync start failed: ${e.message}`)
      return { success: false, error: e.message }
    }
  })

  ipcMain.handle('sync:pause', () => {
    pause()
    return true
  })

  ipcMain.handle('sync:resume', async () => {
    await resume()
    return true
  })

  ipcMain.handle('sync:status', () => {
    return { state: getState() }
  })

  // ---- 同步历史 ----
  ipcMain.handle('sync:get-logs', (_e, params) => getSyncLogs(params || {}))

  ipcMain.handle('sync:clear-logs', () => {
    clearSyncLog()
    return true
  })

  ipcMain.handle('sync:sync-now', () => {
    remotePoller._poll()
    return true
  })

  ipcMain.handle('sync:open-folder', () => {
    const { syncPath } = getSettings()
    if (syncPath) shell.openPath(syncPath)
    return true
  })

  // ---- 自启动 ----
  ipcMain.handle('autostart:get', async () => {
    return await isAutoStartEnabled()
  })

  ipcMain.handle('autostart:set', async (_e, enabled) => {
    return await setAutoStart(enabled)
  })
}
