import request from './request'

export function grantAdmin(data) {
  return request({ url: '/api/permission/admin', method: 'post', data })
}

export function revokeAdmin(deptId, userId) {
  return request({ url: `/api/permission/admin/${deptId}/${userId}`, method: 'delete' })
}

export function getAdmins(deptId) {
  return request({ url: `/api/permission/admins/${deptId}`, method: 'get' })
}

export function grantPermission(data) {
  return request({ url: '/api/permission/grant', method: 'post', data })
}

export function revokePermission(permId) {
  return request({ url: `/api/permission/${permId}`, method: 'delete' })
}

export function getDepartmentPermissions(deptId) {
  return request({ url: `/api/permission/department/${deptId}`, method: 'get' })
}

export function getMyPermissions() {
  return request({ url: '/api/permission/my', method: 'get' })
}

export function getMyAdminDepts() {
  return request({ url: '/api/permission/my-admin-depts', method: 'get', silent: true })
}
