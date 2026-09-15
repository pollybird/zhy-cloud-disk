/**
 * 文件日志：electron-log，写到 userData/logs/sync.log。
 */
import log from 'electron-log'

log.transports.file.level = 'info'
log.transports.file.fileName = 'sync.log'
log.transports.console.level = process.env.NODE_ENV === 'development' ? 'debug' : false

export const logger = log

export function info(msg, ...args) {
  log.info(msg, ...args)
}

export function warn(msg, ...args) {
  log.warn(msg, ...args)
}

export function error(msg, ...args) {
  log.error(msg, ...args)
}

export function debug(msg, ...args) {
  log.debug(msg, ...args)
}
