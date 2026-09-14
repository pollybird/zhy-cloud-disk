import request from './request'

export function createShare(data) {
  return request({ url: '/api/share/create', method: 'post', data })
}

export function getShareInfo(code) {
  return request({ url: '/api/share/info', method: 'get', params: { code } })
}

export function verifySharePassword(code, password) {
  return request({
    url: '/api/share/verify-password',
    method: 'post',
    data: { code, password },
  })
}

export function listShares(params) {
  return request({ url: '/api/share/list', method: 'get', params })
}

export function cancelShare(id) {
  return request({ url: '/api/share/cancel', method: 'delete', params: { id } })
}

/** 匿名分享下载直链（携带访问令牌，无需登录态） */
export function shareDownloadUrl(code, token) {
  const base = `${window.location.origin}/api/share/download`
  const q = new URLSearchParams({ code })
  if (token) q.set('token', token)
  return `${base}?${q.toString()}`
}

/** 公开分享访问页地址 */
export function sharePageUrl(code) {
  return `${window.location.origin}/share/${code}`
}
