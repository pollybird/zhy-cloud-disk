/**
 * Electron 主进程入口：app 生命周期、单实例锁、启动编排。
 */
import { app } from 'electron'
import { createWindow, showWindow } from './window.js'
import { createTray } from './tray.js'
import { registerIpc } from './ipc.js'
import { isConfigured, getSettings } from '../lib/store/settings.js'
import { getAccessToken, getRefreshToken } from '../lib/store/keystore.js'
import { setCredentials, setOnAuthExpired } from '../lib/api/client.js'
import { start, stop } from '../lib/sync/engine.js'
import { emit, EVENTS } from '../lib/events.js'
import { info, error } from '../lib/logger.js'

// Linux 开发环境沙箱权限受限时，可用 ZHY_NO_SANDBOX=1 启动
if (process.env.ZHY_NO_SANDBOX === '1' || process.platform === 'linux' && process.env.NODE_ENV === 'development') {
  app.commandLine.appendSwitch('no-sandbox')
  app.commandLine.appendSwitch('disable-gpu-sandbox')
}

// 单实例锁
const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    // 第二实例：激活已有窗口
    showWindow()
  })

  app.whenReady().then(async () => {
    registerIpc()

    const configured = isConfigured()

    if (!configured) {
      // 首次运行：打开向导
      info('First run: showing setup wizard')
      createWindow()
    } else {
      // 已配置：恢复 token，启动引擎
      const settings = getSettings()
      const access = getAccessToken()
      const refresh = getRefreshToken()
      setCredentials(settings.serverUrl, access, refresh)
      setOnAuthExpired(() => {
        emit(EVENTS.AUTH_EXPIRED)
        showWindow()
      })

      // 创建托盘
      createTray()

      // 启动同步引擎
      try {
        await start()
      } catch (e) {
        error(`Sync engine failed to start: ${e.message}`)
      }

      // 启动后隐藏到托盘
      createWindow()
    }
  })

  // 关闭窗口时隐藏到托盘（不退出）
  app.on('window-all-closed', (e) => {
    // 阻止退出
    e.preventDefault()
  })

  // macOS: 点击 dock 图标重新显示窗口
  app.on('activate', () => {
    showWindow()
  })

  // 退出前清理
  app.on('before-quit', () => {
    app.isQuitting = true
    stop()
  })
}
