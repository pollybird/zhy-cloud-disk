/**
 * BrowserWindow 管理：主界面/向导/设置共用一个窗口。
 */
import { app, BrowserWindow, shell } from 'electron'
import path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

let mainWindow = null

export function createWindow() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.show()
    mainWindow.focus()
    return mainWindow
  }

  mainWindow = new BrowserWindow({
    width: 720,
    height: 560,
    minWidth: 600,
    minHeight: 480,
    title: '钟毓云盘',
    show: true,
    icon: path.join(__dirname, '../../resources/icon.png'),
    webPreferences: {
      preload: path.join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    autoHideMenuBar: true,
    backgroundColor: '#ffffff',
  })

  // 渲染层错误回流到主进程日志，便于排查白屏
  const wc = mainWindow.webContents
  wc.on('console-message', (_e, level, message) => {
    if (level >= 2) console.error(`[renderer ${level}] ${message}`)
  })
  wc.on('did-fail-load', (_e, code, desc) => {
    console.error(`[renderer] did-fail-load: ${code} ${desc}`)
  })
  wc.on('preload-error', (_e, path2, err) => {
    console.error(`[renderer] preload-error ${path2}: ${err}`)
  })
  wc.on('render-process-gone', (_e, details) => {
    console.error(`[renderer] render-process-gone: ${JSON.stringify(details)}`)
  })

  // 开发模式加载 dev server，生产模式加载打包文件
  if (process.env.VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(process.env.VITE_DEV_SERVER_URL)
    wc.openDevTools()
  } else {
    mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'))
  }

  // 外链在系统浏览器打开
  wc.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  // 关闭时隐藏到托盘而非退出；托盘"退出"（app.isQuitting）时放行关闭
  mainWindow.on('close', (e) => {
    if (!app.isQuitting) {
      e.preventDefault()
      mainWindow.hide()
    }
  })

  return mainWindow
}

export function getMainWindow() {
  return mainWindow
}

export function showWindow() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.show()
    mainWindow.focus()
  } else {
    createWindow()
  }
}
