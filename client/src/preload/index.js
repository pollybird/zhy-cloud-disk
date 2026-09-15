/**
 * preload：通过 contextBridge 安全暴露 API 给渲染层。
 */
import { contextBridge, ipcRenderer } from 'electron'

const api = {
  // 设置
  getSettings: () => ipcRenderer.invoke('settings:get'),
  setSettings: (updates) => ipcRenderer.invoke('settings:set', updates),

  // 目录选择
  chooseFolder: () => ipcRenderer.invoke('dialog:chooseFolder'),

  // 认证
  login: (serverUrl, username, password) =>
    ipcRenderer.invoke('auth:login', { serverUrl, username, password }),
  testConnection: (serverUrl) => ipcRenderer.invoke('auth:testConnection', serverUrl),
  logout: () => ipcRenderer.invoke('auth:logout'),

  // 同步控制
  startSync: () => ipcRenderer.invoke('sync:start'),
  pauseSync: () => ipcRenderer.invoke('sync:pause'),
  resumeSync: () => ipcRenderer.invoke('sync:resume'),
  getSyncStatus: () => ipcRenderer.invoke('sync:status'),
  syncNow: () => ipcRenderer.invoke('sync:sync-now'),
  openSyncFolder: () => ipcRenderer.invoke('sync:open-folder'),

  // 同步历史
  getSyncLogs: (params) => ipcRenderer.invoke('sync:get-logs', params),
  clearSyncLogs: () => ipcRenderer.invoke('sync:clear-logs'),

  // 开机自启
  getAutoStart: () => ipcRenderer.invoke('autostart:get'),
  setAutoStart: (enabled) => ipcRenderer.invoke('autostart:set', enabled),

  // 事件监听
  on: (channel, callback) => {
    const validChannels = [
      'sync:progress',
      'sync:state',
      'sync:log',
      'sync:conflict',
      'sync:auth-expired',
    ]
    if (!validChannels.includes(channel)) return
    const handler = (_e, data) => callback(data)
    ipcRenderer.on(channel, handler)
    return () => ipcRenderer.removeListener(channel, handler)
  },
}

contextBridge.exposeInMainWorld('zhy', api)
