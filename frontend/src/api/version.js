import request from './request'

export function listVersions(nodeId) {
  return request({ url: `/api/file/versions/${nodeId}`, method: 'get' })
}

export function downloadVersion(versionId) {
  return request({
    url: '/api/file/version/download',
    method: 'get',
    params: { version_id: versionId },
    responseType: 'blob',
    timeout: 300000,
  })
}

export function restoreVersion(versionId) {
  return request({
    url: '/api/file/version/restore',
    method: 'post',
    data: { version_id: versionId },
  })
}
