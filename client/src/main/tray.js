/**
 * 系统托盘：图标 + 右键菜单。
 */
import { Tray, Menu, nativeImage, shell, app } from 'electron'
import path from 'path'
import { fileURLToPath } from 'url'
import { getSettings } from '../lib/store/settings.js'
import { showWindow } from './window.js'
import { setAutoStart } from './autostart.js'
import { getState } from '../lib/sync/engine.js'
import { remotePoller } from '../lib/sync/remote-poller.js'
import { on } from '../lib/events.js'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

let tray = null

const statusText = {
  idle: '已同步',
  'first-sync': '首次同步中...',
  syncing: '同步中...',
  paused: '已暂停',
  error: '同步错误',
}

export function createTray() {
  const iconPath = path.join(__dirname, '../../resources/icon.png')
  let icon
  try {
    icon = nativeImage.createFromPath(iconPath)
    if (icon.isEmpty()) {
      icon = nativeImage.createEmpty()
    }
  } catch {
    icon = nativeImage.createEmpty()
  }

  tray = new Tray(icon)
  tray.setToolTip('钟毓云盘')
  updateContextMenu()

  tray.on('click', () => {
    showWindow()
  })

  on('state-change', () => updateContextMenu())
}

export function updateContextMenu() {
  if (!tray) return
  const settings = getSettings()
  const currentState = getState()
  const menu = Menu.buildFromTemplate([
    { label: `钟毓云盘 · ${statusText[currentState] || currentState}`, enabled: false },
    { type: 'separator' },
    { label: '打开主界面', click: () => showWindow() },
    {
      label: '打开同步文件夹',
      click: () => {
        if (settings.syncPath) shell.openPath(settings.syncPath)
      },
    },
    {
      label: '立即同步',
      click: () => {
        remotePoller._poll()
      },
    },
    { label: '设置...', click: () => showWindow() },
    { type: 'separator' },
    {
      label: '开机自启',
      type: 'checkbox',
      checked: settings.autoStart,
      click: async (item) => {
        await setAutoStart(item.checked)
      },
    },
    { type: 'separator' },
    {
      label: '退出',
      click: () => {
        app.isQuitting = true
        app.quit()
      },
    },
  ])
  tray.setContextMenu(menu)
}
