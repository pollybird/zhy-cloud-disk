import request from './request'

export function getGlobalLogs(params) {
  return request({ url: '/api/log/global', method: 'get', params })
}

export function getDepartmentLogs(deptId, params) {
  return request({ url: `/api/log/department/${deptId}`, method: 'get', params })
}
