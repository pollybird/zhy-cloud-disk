/**
 * axios 实例：统一 baseURL、Bearer token 注入、响应解包、401 自动 refresh。
 * 响应格式：{ code, msg, data }，code === 0 为成功。
 */
import axios from 'axios'

let accessToken = null
let refreshToken = null
let serverUrl = ''
let onAuthExpired = null  // token 过期回调（由 engine 注入，触发重登录提示）

export function setCredentials(server, access, refresh) {
  serverUrl = server.replace(/\/$/, '')
  accessToken = access
  refreshToken = refresh
}

export function getAccessToken() {
  return accessToken
}

export function setOnAuthExpired(fn) {
  onAuthExpired = fn
}

export function getServerUrl() {
  return serverUrl
}

const http = axios.create({ timeout: 120000 })

// 请求拦截：注入 baseURL 和 Authorization
http.interceptors.request.use((config) => {
  config.baseURL = serverUrl
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`
  }
  return config
})

// 响应拦截：解包 { code, msg, data }
http.interceptors.response.use(
  (res) => {
    const body = res.data
    // 二进制流（下载）直接返回
    if (res.config.responseType === 'stream' || res.config.responseType === 'blob') {
      return res
    }
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code === 0) return body
      const err = new Error(body.msg || '请求失败')
      err.code = body.code
      err.data = body.data
      throw err
    }
    return body
  },
  async (error) => {
    const cfg = error.config || {}
    const url = cfg.url || ''
    // 登录/刷新请求本身返回 401 时直接抛错，避免无限刷新循环
    const isAuthRequest = url.includes('/api/login') || url.includes('/api/auth/refresh')
    // 401 自动 refresh 一次；无 refreshToken 或已重试过时直接触发过期回调
    if (error.response && error.response.status === 401 && !isAuthRequest && !cfg._retried) {
      cfg._retried = true
      if (refreshToken) {
        try {
          const res = await axios.post(`${serverUrl}/api/auth/refresh`, null, {
            headers: { Authorization: `Bearer ${refreshToken}` },
          })
          const body = res.data
          if (body.code === 0 && body.data && body.data.access_token) {
            accessToken = body.data.access_token
            refreshToken = body.data.refresh_token || refreshToken
            // 重试原请求
            cfg.headers.Authorization = `Bearer ${accessToken}`
            return http(cfg)
          }
        } catch {
          // refresh 失败
        }
      }
      if (onAuthExpired) onAuthExpired()
    }
    throw error
  }
)

export default http
