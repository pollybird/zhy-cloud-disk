/**
 * 开机自启：auto-launch 封装。
 */
import AutoLaunch from 'auto-launch'
import { app } from 'electron'

const launcher = new AutoLaunch({
  name: '钟毓云盘',
  path: app.getPath('exe'),
})

export async function enableAutoStart() {
  try {
    await launcher.enable()
    return true
  } catch (e) {
    return false
  }
}

export async function disableAutoStart() {
  try {
    await launcher.disable()
    return true
  } catch (e) {
    return false
  }
}

export async function isAutoStartEnabled() {
  try {
    return await launcher.isEnabled()
  } catch {
    return false
  }
}

export async function setAutoStart(enabled) {
  if (enabled) {
    return enableAutoStart()
  } else {
    return disableAutoStart()
  }
}
