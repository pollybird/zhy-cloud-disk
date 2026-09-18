/**
 * 部门网盘显式传输编排（与同步引擎无关）：
 * - planUploads：上传前逐个查重（同内容 skip / 异内容 conflict / 新文件 upload）
 * - executeUploads：按用户对冲突的决定顺序上传
 * - downloadItems：把选中的文件/文件夹递归下载到用户指定目录
 *
 * IO 与网络依赖均可注入，便于单测。
 */
import path from 'path'
import fsp from 'fs/promises'
import { computeMd5 } from '../sync/hasher.js'
import { downloadFile } from '../api/file.js'
import {
  checkDeptDuplicate,
  listDeptFiles,
} from '../api/department.js'
import { uploadLocal } from '../sync/chunk-uploader.js'

const PAGE_SIZE = 200

/** 去掉 Windows 非法文件名字符（Linux/macOS 下也统一处理，保证跨平台拷贝安全）。 */
export function sanitizeName(name) {
  return String(name).replace(/[\\/:*?"<>|]/g, '_')
}

/**
 * 上传前查重计划。
 * @param {string[]} filePaths 本地文件绝对路径
 * @param {object} ctx
 * @returns {Promise<Array<{path:string,fileName:string,fileSize:number,fileHash:string,action:string,existing?:object,error?:string}>>}
 */
export async function planUploads(filePaths, {
  departmentId,
  parentId = null,
  stat = (p) => fsp.stat(p),
  md5 = computeMd5,
  check = checkDeptDuplicate,
} = {}) {
  const plans = []
  for (const filePath of filePaths) {
    const fileName = path.basename(filePath)
    try {
      const st = await stat(filePath)
      if (!st.isFile()) continue
      const fileHash = await md5(filePath)
      const dup = await check({ parentId, fileName, fileHash, departmentId })
      plans.push({
        path: filePath,
        fileName,
        fileSize: st.size,
        fileHash,
        action: dup.action || 'upload',
        existing: dup.existing || null,
      })
    } catch (e) {
      plans.push({ path: filePath, fileName, fileSize: 0, fileHash: null, action: 'error', error: e.message })
    }
  }
  return plans
}

/**
 * 顺序执行上传。
 * @param {Array} plans planUploads 的结果
 * @param {object} ctx
 * @param {boolean} ctx.overwrite 同名异内容是否覆盖（用户一次决定，对全部冲突生效）
 * @param {(p:{index:number,total:number,fileName:string,percent:number})=>void} [ctx.onProgress]
 * @returns {Promise<{success:Array, skipped:Array, failed:Array}>}
 */
export async function executeUploads(plans, {
  departmentId,
  parentId = null,
  overwrite = false,
  upload = uploadDeptFile,
  onProgress = null,
} = {}) {
  const todo = plans.filter((p) => {
    if (p.action === 'skip' || p.action === 'error') return false
    if (p.action === 'conflict' && !overwrite) return false
    return true
  })
  const skipped = plans.filter(
    (p) => p.action === 'skip' || (p.action === 'conflict' && !overwrite) || p.action === 'error'
  )
  const success = []
  const failed = []

  for (let i = 0; i < todo.length; i += 1) {
    const p = todo[i]
    const emit = (percent, instant = false) => onProgress?.({
      index: i + 1, total: todo.length, fileName: p.fileName, percent,
      mode: instant ? 'instant' : undefined,
    })
    emit(0)
    try {
      const payload = {
        departmentId,
        parentId,
        fileHash: p.fileHash,
        onProgress: emit,
      }
      if (p.action === 'conflict') {
        payload.mode = 'overwrite'
        payload.overwriteId = p.existing?.id
      }
      const res = await upload(p.path, payload)
      // uploadLocal 返回 { node, instant }；兼容旧封装 { success:[node...] }
      const node = res?.node || res?.success?.[0] || res
      success.push({ plan: p, node, instant: Boolean(res?.instant) })
      emit(100, res?.instant)
    } catch (e) {
      failed.push({ plan: p, message: e.message })
      emit(100)
    }
  }
  return { success, skipped, failed }
}

/**
 * 递归展开待下载节点为平铺任务（同时完成分页拉取与文件夹发现）。
 * @param {Array<{id:number,file_name:string,is_folder:boolean,department_id:number}>} nodes
 * @param {string} targetDir 用户选定的本地目录
 */
async function collectDownloads(nodes, targetDir, listFiles) {
  const tasks = []
  const walk = async (node, dir) => {
    if (!node.is_folder) {
      tasks.push({ id: node.id, fileName: node.file_name, dest: dir })
      return
    }
    const sub = path.join(dir, sanitizeName(node.file_name))
    let page = 1
    // 部门 id 挂在节点上；顶层选择项同样带 department_id
    const departmentId = node.department_id
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const data = await listFiles({ departmentId, parentId: node.id, page, size: PAGE_SIZE })
      for (const item of data.items || []) {
        await walk(item, sub)
      }
      if (page * PAGE_SIZE >= (data.total || 0)) break
      page += 1
    }
  }
  for (const node of nodes) {
    // eslint-disable-next-line no-await-in-loop
    await walk(node, targetDir)
  }
  return tasks
}

/**
 * 下载选中的文件/文件夹到本地目标目录（保留目录结构）。
 * @returns {Promise<{success:number, failed:Array<{name:string,message:string}>}>}
 */
export async function downloadItems(nodes, targetDir, {
  listFiles = listDeptFiles,
  download = downloadFile,
  onProgress = null,
} = {}) {
  const tasks = await collectDownloads(nodes, targetDir, listFiles)
  const failed = []
  let done = 0

  for (const task of tasks) {
    const fullPath = path.join(task.dest, sanitizeName(task.fileName))
    try {
      await fsp.mkdir(task.dest, { recursive: true })
      // Windows 下 fs.rename 不能覆盖已存在文件，先删除旧文件
      try {
        await fsp.unlink(fullPath)
      } catch (e) {
        if (e.code !== 'ENOENT') throw e
      }
      await download(task.id, fullPath, {
        expectedSize: task.fileSize,
        expectedHash: task.fileHash,
      })
      done += 1
    } catch (e) {
      failed.push({ name: task.fileName, message: e.message })
    }
    onProgress?.({
      phase: 'download',
      current: done + failed.length,
      total: tasks.length,
      fileName: task.fileName,
    })
  }
  return { success: done, failed }
}
