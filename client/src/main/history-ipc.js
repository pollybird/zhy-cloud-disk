/**
 * 回收站与历史版本 IPC 通道（1.3.0）。
 *
 * 通道清单：
 *   trash:list / trash:restore / trash:purge / trash:empty
 *   versions:list / versions:download / versions:restore
 *
 * 统一返回 { success:true, data } / { success:false, error }。
 */
import { ipcMain, dialog } from 'electron'
import {
  listTrash,
  restoreTrashItem,
  purgeTrashItem,
  emptyTrash,
  listVersions,
  downloadVersion,
  restoreVersion,
} from '../lib/api/file.js'
import { error } from '../lib/logger.js'

let registered = false

function handle(channel, fn) {
  ipcMain.handle(channel, async (_event, payload) => {
    try {
      const data = await fn(payload || {})
      return { success: true, data }
    } catch (e) {
      error(`[history] ${channel} failed: ${e.message}`)
      return { success: false, error: e.message }
    }
  })
}

export function registerHistoryIpc() {
  if (registered) return
  registered = true

  handle('trash:list', ({ scope, departmentId }) =>
    listTrash({ scope: scope === 'department' ? 'department' : 'personal', departmentId }))
  handle('trash:restore', ({ id }) => restoreTrashItem(id))
  handle('trash:purge', ({ id }) => purgeTrashItem(id))
  handle('trash:empty', ({ scope, departmentId }) =>
    emptyTrash({ scope: scope === 'department' ? 'department' : 'personal', departmentId }))

  handle('versions:list', ({ nodeId }) => listVersions(nodeId))
  handle('versions:restore', ({ versionId }) => restoreVersion(versionId))
  handle('versions:download', async ({ versionId, fileName }) => {
    const result = await dialog.showSaveDialog({
      defaultPath: fileName || 'download',
    })
    if (result.canceled || !result.filePath) return { canceled: true }
    await downloadVersion(versionId, result.filePath)
    return { canceled: false, filePath: result.filePath }
  })
}

