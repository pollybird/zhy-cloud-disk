/**
 * 认证接口封装。
 */
import http, { setCredentials } from './client.js'

export async function login(serverUrl, username, password) {
  // 先探测服务器连通性
  const pingRes = await http.get(`${serverUrl}/api/ping`)
  if (pingRes.code !== 0) {
    throw new Error('服务器连接失败')
  }
  if (pingRes.data && pingRes.data.installed === false) {
    throw new Error('服务器尚未完成安装向导，请先在浏览器中完成安装')
  }

  // 登录
  const res = await http.post(`${serverUrl}/api/login`, { username, password })
  const { access_token, refresh_token, user } = res.data
  setCredentials(serverUrl, access_token, refresh_token)
  return { access_token, refresh_token, user }
}

export async function refresh(refreshTokenValue) {
  const res = await http.post('/api/auth/refresh', null, {
    headers: { Authorization: `Bearer ${refreshTokenValue}` },
  })
  return res.data
}

export function logout() {
  setCredentials('', null, null)
}

export async function testConnection(serverUrl) {
  const res = await http.get(`${serverUrl.replace(/\/$/, '')}/api/ping`)
  return res
}
