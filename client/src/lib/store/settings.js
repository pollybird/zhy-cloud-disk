/**
 * 设置持久化：electron-store。
 * 存储服务器地址、同步路径、开机自启、轮询间隔、冲突策略。
 */
import Store from 'electron-store'

const store = new Store({
  name: 'settings',
  defaults: {
    serverUrl: '',
    username: '',
    syncPath: '',
    autoStart: false,
    pollInterval: 60,       // 秒
    conflictStrategy: 'keep-both',  // keep-both | last-write-wins
    configured: false,       // 是否已完成首次配置
  },
})

export function getSettings() {
  return {
    serverUrl: store.get('serverUrl'),
    username: store.get('username'),
    syncPath: store.get('syncPath'),
    autoStart: store.get('autoStart'),
    pollInterval: store.get('pollInterval'),
    conflictStrategy: store.get('conflictStrategy'),
    configured: store.get('configured'),
  }
}

export function getSetting(key) {
  return store.get(key)
}

export function setSetting(key, value) {
  store.set(key, value)
}

export function setSettings(updates) {
  Object.entries(updates).forEach(([k, v]) => store.set(k, v))
}

export function isConfigured() {
  return (
    store.get('configured') === true && Boolean(store.get('serverUrl')) && Boolean(store.get('syncPath'))
  )
}

export function resetSettings() {
  store.set('configured', false)
  store.set('serverUrl', '')
  store.set('username', '')
  store.set('syncPath', '')
}

export default store
