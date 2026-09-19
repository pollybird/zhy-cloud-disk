/**
 * preload：通过 contextBridge 安全暴露 API 给渲染层。
 */
import { contextBridge, ipcRenderer, webUtils } from 'electron'

/**
 * IPC 边界净化：剥离 Vue reactive Proxy，转为可结构化克隆的纯对象。
 * 渲染层传入的表格行/列表常为响应式代理，直接 invoke 会抛
 * "An object could not be cloned."。此处入参均为文件节点等纯 DTO，
 * JSON 往返可安全覆盖。
 */
function plain(value) {
  if (value === null || typeof value !== 'object') return value
  return JSON.parse(JSON.stringify(value))
}

function invoke(channel, ...args) {
  return ipcRenderer.invoke(channel, ...args.map(plain))
}

const api = {
  // 设置
  getSettings: () => invoke('settings:get'),
  setSettings: (updates) => invoke('settings:set', updates),

  // 目录选择
  chooseFolder: () => invoke('dialog:chooseFolder'),

  // 认证
  login: (serverUrl, username, password) =>
    invoke('auth:login', { serverUrl, username, password }),
  testConnection: (serverUrl) => invoke('auth:testConnection', serverUrl),
  logout: () => invoke('auth:logout'),

  // 同步控制
  startSync: () => invoke('sync:start'),
  pauseSync: () => invoke('sync:pause'),
  resumeSync: () => invoke('sync:resume'),
  getSyncStatus: () => invoke('sync:status'),
  syncNow: () => invoke('sync:sync-now'),
  openSyncFolder: () => invoke('sync:open-folder'),

  // 同步历史
  getSyncLogs: (params) => invoke('sync:get-logs', params),
  clearSyncLogs: () => invoke('sync:clear-logs'),

  // 开机自启
  getAutoStart: () => invoke('autostart:get'),
  setAutoStart: (enabled) => invoke('autostart:set', enabled),

  // 部门网盘（在线浏览，不同步到本地）
  dept: {
    featureFlags: () => invoke('dept:feature-flags'),
    tree: () => invoke('dept:tree'),
    list: (params) => invoke('dept:list', params),
    folders: (params) => invoke('dept:folders', params),
    createFolder: (params) => invoke('dept:create-folder', params),
    rename: (id, fileName) => invoke('dept:rename', { id, fileName }),
    move: (id, targetParentId) => invoke('dept:move', { id, targetParentId }),
    remove: (id) => invoke('dept:delete', { id }),
    openFile: (node) => invoke('dept:open-file', node),
    download: (nodes, targetDir) =>
      invoke('dept:download', { nodes, targetDir }),
    chooseFiles: () => invoke('dept:choose-files'),
    statPaths: (paths) => invoke('dept:stat-paths', { paths }),
    walkDir: (dir) => invoke('dept:walk-dir', { dir }),
    planUploads: (paths, departmentId, parentId) =>
      invoke('dept:plan-uploads', { paths, departmentId, parentId }),
    upload: (plans, departmentId, parentId, overwrite) =>
      invoke('dept:upload', { plans, departmentId, parentId, overwrite }),
  },

  // 回收站与历史版本（1.3.0，个人/部门复用）
  trash: {
    list: (params) => invoke('trash:list', params),
    restore: (id) => invoke('trash:restore', { id }),
    purge: (id) => invoke('trash:purge', { id }),
    empty: (params) => invoke('trash:empty', params),
  },
  versions: {
    list: (nodeId) => invoke('versions:list', { nodeId }),
    restore: (versionId) => invoke('versions:restore', { versionId }),
    download: (versionId, fileName) =>
      invoke('versions:download', { versionId, fileName }),
  },

  // Electron 32+ 拖入文件真实路径必须经 webUtils 获取
  getPathForFile: (file) => webUtils.getPathForFile(file),

  // 事件监听
  on: (channel, callback) => {
    const validChannels = [
      'sync:progress',
      'sync:state',
      'sync:log',
      'sync:conflict',
      'sync:auth-expired',
      'dept:progress',
      'dept:toast',
    ]
    if (!validChannels.includes(channel)) return
    const handler = (_e, data) => callback(data)
    ipcRenderer.on(channel, handler)
    return () => ipcRenderer.removeListener(channel, handler)
  },
}

contextBridge.exposeInMainWorld('zhy', api)
