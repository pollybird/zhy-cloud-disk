/**
 * 部门网盘接口封装（在线浏览模式，不走个人同步引擎）。
 * 后端路由：
 *   GET  /api/system/feature-flags
 *   GET  /api/department/tree
 *   GET  /api/file/list?department_id=&parent_id=&page=&size=
 *   GET  /api/file/folders?department_id=&parent_id=
 *   POST /api/folder/create        { parent_id, file_name, department_id }
 *   POST /api/file/check-duplicate { parent_id, file_name, file_hash, department_id }
 *   POST /api/file/upload          multipart: files / department_id / parent_id / file_hash / mode / overwrite_id
 * 重命名 / 移动 / 删除复用 file.js（服务端按节点 id 自行鉴权），下载复用 downloadFile。
 */
import http from './client.js'
import fs from 'fs'
import path from 'path'

/** 功能开关：部门网盘是否启用。 */
export async function getFeatureFlags() {
  const res = await http.get('/api/system/feature-flags')
  return res.data
}

/** 当前用户可见（my_permission !== none）的部门树。 */
export async function getDepartmentTree() {
  const res = await http.get('/api/department/tree')
  return res.data || []
}

/**
 * 部门文件列表（分页）。
 * @returns {Promise<{items:Array,total:number,access:string,breadcrumb:Array}>}
 */
export async function listDeptFiles({ departmentId, parentId = null, page = 1, size = 200 }) {
  const res = await http.get('/api/file/list', {
    params: {
      department_id: departmentId,
      parent_id: parentId ?? '',
      page,
      size,
    },
  })
  return res.data
}

/** 部门目录下的直属子文件夹（移动弹窗用）。 */
export async function listDeptFolders(parentId = null, departmentId) {
  const res = await http.get('/api/file/folders', {
    params: {
      department_id: departmentId,
      parent_id: parentId ?? '',
    },
  })
  return res.data.items || []
}

/** 在部门网盘内新建文件夹。 */
export async function createDeptFolder(parentId, fileName, departmentId) {
  const res = await http.post('/api/folder/create', {
    parent_id: parentId ?? null,
    file_name: fileName,
    department_id: departmentId,
  })
  return res.data
}

/**
 * 上传前查重。
 * @returns {Promise<{action:'skip'|'conflict'|'upload', existing?:object}>}
 */
export async function checkDeptDuplicate({ parentId, fileName, fileHash, departmentId }) {
  const res = await http.post('/api/file/check-duplicate', {
    parent_id: parentId ?? null,
    file_name: fileName,
    file_hash: fileHash,
    department_id: departmentId,
  })
  return res.data
}

/**
 * 上传单个本地文件到部门网盘。
 * @param {string} filePath 本地文件绝对路径
 * @param {object} opts
 * @param {number} opts.departmentId 目标部门 id
 * @param {number|null} [opts.parentId] 目标文件夹 id
 * @param {string} [opts.fileHash] MD5
 * @param {'normal'|'overwrite'} [opts.mode]
 * @param {number} [opts.overwriteId] 被覆盖的服务端文件 id
 * @param {(percent:number)=>void} [opts.onProgress]
 */
export async function uploadDeptFile(filePath, {
  departmentId,
  parentId = null,
  fileHash = null,
  mode = 'normal',
  overwriteId = null,
  onProgress = null,
} = {}) {
  const fileName = path.basename(filePath)
  const fd = new FormData()
  fd.append('files', new Blob([await fs.promises.readFile(filePath)]), fileName)
  fd.append('department_id', String(departmentId))
  if (parentId) fd.append('parent_id', String(parentId))
  if (fileHash) fd.append('file_hash', fileHash)
  if (mode !== 'normal') fd.append('mode', mode)
  if (overwriteId) fd.append('overwrite_id', String(overwriteId))

  const res = await http.post('/api/file/upload', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
    maxContentLength: Infinity,
    maxBodyLength: Infinity,
    timeout: 0,
    onUploadProgress: (e) => {
      if (onProgress && e.total && e.total > 0) {
        onProgress(Math.min(99, Math.round((e.loaded / e.total) * 100)))
      }
    },
  })
  return res.data
}
