import request from './request'

export function listFiles(params) {
  return request({ url: '/api/file/list', method: 'get', params })
}

export function listChildFolders(parent_id, department_id) {
  const params = {}
  if (parent_id) params.parent_id = parent_id
  if (department_id) params.department_id = department_id
  return request({
    url: '/api/file/folders',
    method: 'get',
    params,
  })
}

export function uploadFiles(formData, onProgress, signal) {
  return request({
    url: '/api/file/upload',
    method: 'post',
    data: formData,
    timeout: 0,
    headers: { 'Content-Type': 'multipart/form-data' },
    signal,
    onUploadProgress: (e) => {
      if (onProgress && e.total && e.total > 0) {
        onProgress(Math.min(99, Math.round((e.loaded / e.total) * 100)))
      }
    },
  })
}

export function checkDuplicate(payload) {
  return request({
    url: '/api/file/check-duplicate',
    method: 'post',
    data: payload,
    silent: true,
  })
}

export function createFolder(parent_id, file_name, department_id) {
  return request({
    url: '/api/folder/create',
    method: 'post',
    data: {
      parent_id,
      file_name,
      ...(department_id ? { department_id } : {}),
    },
  })
}

export function renameFile(id, file_name) {
  return request({
    url: '/api/file/rename',
    method: 'put',
    data: { id, file_name },
  })
}

export function moveFile(id, target_parent_id) {
  return request({
    url: '/api/file/move',
    method: 'put',
    data: { id, target_parent_id },
  })
}

export function deleteFile(id) {
  return request({
    url: '/api/file/delete',
    method: 'delete',
    data: { id },
  })
}

export function downloadFile(id) {
  return request({
    url: '/api/file/download',
    method: 'get',
    params: { id },
    responseType: 'blob',
    timeout: 0,
  })
}
