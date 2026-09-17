/**
 * 部门网盘 IPC 通道（在线浏览模式，与个人同步引擎完全独立）。
 *
 * 通道清单：
 *   dept:feature-flags / dept:tree / dept:list / dept:folders
 *   dept:create-folder / dept:rename / dept:move / dept:delete
 *   dept:open-file（双击：临时下载 + 系统打开 + 保存自动回传）
 *   dept:download（选中文件/文件夹下载到本地目录）
 *   dept:choose-files（上传按钮：系统文件多选框）
 *   dept:stat-paths / dept:walk-dir（拖拽：类型识别与目录递归）
 *   dept:plan-uploads（上传前查重）/ dept:upload（执行上传）
 *
 * 统一返回 { success:true, data } / { success:false, error }。
 */
import { ipcMain, dialog } from 'electron'
import path from 'path'
import fsp from 'fs/promises'
import {
  getFeatureFlags,
  getDepartmentTree,
  listDeptFiles,
  listDeptFolders,
  createDeptFolder,
} from '../lib/api/department.js'
import { renameNode, moveNode, deleteNode } from '../lib/api/file.js'
import { createTempFileManager } from '../lib/dept/temp-file-manager.js'
import { planUploads, executeUploads, downloadItems } from '../lib/dept/dept-transfer.js'
import { emit, EVENTS } from '../lib/events.js'
import { getMainWindow } from './window.js'
import { error } from '../lib/logger.js'

let registered = false
let manager = null

function broadcast(channel, data) {
  getMainWindow()?.webContents?.send(channel, data)
}

function getManager() {
  if (!manager) {
    manager = createTempFileManager({
      onToast: (toast) => broadcast(EVENTS.DEPT_TOAST, toast),
    })
  }
  return manager
}

/** 供 main/index.js 在退出时清理临时目录。 */
export function getDeptTempManager() {
  return getManager()
}

function handle(channel, fn) {
  ipcMain.handle(channel, async (_event, payload) => {
    try {
      const data = await fn(payload || {})
      return { success: true, data }
    } catch (e) {
      error(`[dept] ${channel} failed: ${e.message}`)
      return { success: false, error: e.message }
    }
  })
}

/** 递归枚举目录内全部文件（拖拽文件夹上传）。 */
async function walkDir(dir) {
  const out = []
  const walk = async (d) => {
    const entries = await fsp.readdir(d, { withFileTypes: true })
    for (const entry of entries) {
      const full = path.join(d, entry.name)
      if (entry.isDirectory()) {
        // eslint-disable-next-line no-await-in-loop
        await walk(full)
      } else if (entry.isFile()) {
        out.push(full)
      }
    }
  }
  await walk(dir)
  return out
}

export function registerDeptIpc() {
  if (registered) return
  registered = true

  handle('dept:feature-flags', async () => getFeatureFlags())
  handle('dept:tree', async () => getDepartmentTree())
  handle('dept:list', ({ departmentId, parentId, page, size }) =>
    listDeptFiles({ departmentId, parentId, page, size }))
  handle('dept:folders', ({ departmentId, parentId }) =>
    listDeptFolders(parentId, departmentId))
  handle('dept:create-folder', ({ departmentId, parentId, fileName }) =>
    createDeptFolder(parentId, fileName, departmentId))
  handle('dept:rename', ({ id, fileName }) => renameNode(id, fileName))
  handle('dept:move', ({ id, targetParentId }) => moveNode(id, targetParentId))
  handle('dept:delete', ({ id }) => deleteNode(id))

  // 双击：下载到临时目录并系统打开（read_write 保存自动回传，read_only 强制只读）
  handle('dept:open-file', async (node) => getManager().openForEdit(node))

  // 选中下载：文件/文件夹递归落盘到用户选择的目录
  handle('dept:download', async ({ nodes, targetDir }) =>
    downloadItems(nodes, targetDir, {
      onProgress: (p) => broadcast(EVENTS.DEPT_PROGRESS, p),
    }))

  // 上传按钮：多选本地文件
  handle('dept:choose-files', async () => {
    const result = await dialog.showOpenDialog({
      properties: ['openFile', 'multiSelections'],
    })
    return result.canceled ? [] : result.filePaths
  })

  // 拖拽：区分文件与目录
  handle('dept:stat-paths', async ({ paths: paths0 }) => {
    const files = []
    const dirs = []
    await Promise.all(
      (paths0 || []).map(async (p) => {
        try {
          const st = await fsp.stat(p)
          if (st.isDirectory()) dirs.push(p)
          else if (st.isFile()) files.push(p)
        } catch {
          // 无法访问的拖入项忽略
        }
      })
    )
    return { files, dirs }
  })

  handle('dept:walk-dir', async ({ dir }) => walkDir(dir))

  // 上传两步：先查重（渲染层据此询问冲突覆盖），再按决定执行
  handle('dept:plan-uploads', async ({ paths: paths0, departmentId, parentId }) =>
    planUploads(paths0, { departmentId, parentId }))
  handle('dept:upload', async ({ plans, departmentId, parentId, overwrite }) =>
    executeUploads(plans, {
      departmentId,
      parentId,
      overwrite,
      onProgress: (p) => broadcast(EVENTS.DEPT_PROGRESS, { phase: 'upload', ...p }),
    }))
}
