/**
 * 简易事件总线：同步引擎状态广播给托盘和 UI。
 */
import { EventEmitter } from 'events'

const bus = new EventEmitter()
bus.setMaxListeners(50)

export const EVENTS = {
  STATE_CHANGE: 'state-change',       // idle | syncing | error | paused | first-sync
  PROGRESS: 'progress',               // { current, total, fileName }
  CONFLICT: 'conflict',                // { localPath, serverNode }
  AUTH_EXPIRED: 'auth-expired',
  LOG: 'log',                          // { level, message }
}

export function emit(event, data) {
  bus.emit(event, data)
}

export function on(event, handler) {
  bus.on(event, handler)
  return () => bus.off(event, handler)
}

export function off(event, handler) {
  bus.off(event, handler)
}

export default bus
