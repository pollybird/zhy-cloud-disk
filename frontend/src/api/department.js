import request from './request'

export function getDepartmentTree() {
  return request({ url: '/api/department/tree', method: 'get' })
}

export function createDepartment(data) {
  return request({ url: '/api/department', method: 'post', data })
}

export function updateDepartment(deptId, data) {
  return request({ url: `/api/department/${deptId}`, method: 'put', data })
}

export function deleteDepartment(deptId) {
  return request({ url: `/api/department/${deptId}`, method: 'delete' })
}

export function moveDepartment(deptId, newParentId) {
  return request({
    url: `/api/department/${deptId}/move`,
    method: 'post',
    data: { new_parent_id: newParentId },
  })
}

export function getMembers(deptId) {
  return request({ url: `/api/department/${deptId}/members`, method: 'get' })
}

export function getCandidateUsers(deptId, keyword) {
  return request({
    url: `/api/department/${deptId}/candidate-users`,
    method: 'get',
    params: keyword ? { keyword } : {},
  })
}

export function addMember(deptId, data) {
  return request({ url: `/api/department/${deptId}/members`, method: 'post', data })
}

export function removeMember(deptId, userId) {
  return request({ url: `/api/department/${deptId}/members/${userId}`, method: 'delete' })
}

export function updateMember(deptId, userId, data) {
  return request({ url: `/api/department/${deptId}/members/${userId}`, method: 'put', data })
}
