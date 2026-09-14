import request from './request'

export function getUserInfo() {
  return request({ url: '/api/user/info', method: 'get' })
}

export function changePassword(old_password, new_password) {
  return request({
    url: '/api/user/pwd',
    method: 'put',
    data: { old_password, new_password },
  })
}

export function listUsers(params) {
  return request({ url: '/api/admin/users', method: 'get', params })
}

export function updateUserQuota(user_id, total_storage) {
  return request({
    url: `/api/admin/users/${user_id}/quota`,
    method: 'put',
    data: { total_storage },
  })
}

export function setUserStatus(user_id, status) {
  return request({
    url: `/api/admin/users/${user_id}/status`,
    method: 'put',
    data: { status },
  })
}

export function getAdminSettings() {
  return request({ url: '/api/admin/settings', method: 'get' })
}

export function updateAdminSettings(data) {
  return request({ url: '/api/admin/settings', method: 'put', data })
}

export function createUser(data) {
  return request({ url: '/api/admin/users', method: 'post', data })
}

export function updateUser(user_id, data) {
  return request({ url: `/api/admin/users/${user_id}`, method: 'put', data })
}
