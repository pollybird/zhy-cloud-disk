import request from './request'

export function listTrash(params) {
  return request({ url: '/api/file/trash', method: 'get', params })
}

export function restoreTrash(id) {
  return request({ url: '/api/file/trash/restore', method: 'post', data: { id } })
}

export function purgeTrashItem(id) {
  return request({ url: '/api/file/trash/item', method: 'delete', data: { id } })
}

export function emptyTrash(params) {
  return request({ url: '/api/file/trash', method: 'delete', params })
}
