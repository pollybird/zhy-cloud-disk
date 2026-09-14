import request from './request'

export function login(username, password) {
  return request({
    url: '/api/login',
    method: 'post',
    data: { username, password },
  })
}

export function register(username, email, password) {
  return request({
    url: '/api/register',
    method: 'post',
    data: { username, email, password },
  })
}

export function getRegisterStatus() {
  return request({ url: '/api/auth/register-status', method: 'get' })
}

export function refreshToken(refresh_token) {
  return request({
    url: '/api/auth/refresh',
    method: 'post',
    headers: { Authorization: `Bearer ${refresh_token}` },
  })
}

export function logout() {
  return request({ url: '/api/logout', method: 'post' })
}
