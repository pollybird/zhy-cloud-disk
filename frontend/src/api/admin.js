import request from './request'

// 监控仪表盘
export function getMetrics() {
  return request({ url: '/api/admin/metrics', method: 'get' })
}

// 备份恢复
export function startBackup() {
  return request({ url: '/api/admin/backup', method: 'post' })
}

export function testBackupConnection(data) {
  return request({ url: '/api/admin/backup/test-connection', method: 'post', data })
}

export function listBackups() {
  return request({ url: '/api/admin/backups', method: 'get' })
}

export function downloadBackup(recordId) {
  return request({
    url: `/api/admin/backup/download/${recordId}`,
    method: 'get',
    responseType: 'blob',
    timeout: 300000,
  })
}

export function deleteBackup(recordId) {
  return request({ url: `/api/admin/backup/${recordId}`, method: 'delete' })
}

// 从服务器已有备份记录恢复（无记录的游离文件可用 remote_filename）
export function restoreBackup(payload) {
  return request({
    url: '/api/admin/backup/restore',
    method: 'post',
    data: { confirm: true, ...payload },
    timeout: 300000,
  })
}

// 上传本地备份 zip 恢复
export function restoreBackupUpload(file, onProgress) {
  const form = new FormData()
  form.append('file', file)
  form.append('confirm', 'true')
  return request({
    url: '/api/admin/backup/restore',
    method: 'post',
    data: form,
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 600000,
    onUploadProgress: onProgress,
  })
}
