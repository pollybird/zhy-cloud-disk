import axios from 'axios'
import { ElMessage } from 'element-plus'

const service = axios.create({
  baseURL: '/',
  timeout: 30000,
})

// 请求拦截：注入 JWT
service.interceptors.request.use((config) => {
  const token = localStorage.getItem('zhy_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截：统一处理 {code,msg,data}
service.interceptors.response.use(
  async (response) => {
    const res = response.data
    // blob 请求：成功直接放行，失败时服务端返回的是 JSON 错误体
    if (response.config.responseType === 'blob' && res instanceof Blob) {
      if (res.type && res.type.includes('application/json')) {
        const text = await res.text()
          let payload = {}
          try {
            payload = JSON.parse(text)
          } catch (e) {
            payload = { code: -1, msg: '下载失败' }
          }
          if (!response.config.silent) ElMessage.error(payload.msg || '下载失败')
          return Promise.reject(payload)
      }
      return response
    }
    if (res && typeof res === 'object' && 'code' in res) {
      if (res.code === 0) {
        return res
      }
      if (!response.config.silent) {
        ElMessage.error(res.msg || '请求失败')
      }
      return Promise.reject(res)
    }
    return response
  },
  (error) => {
    // 主动取消的请求（如取消上传）静默处理
    if (error.code === 'ERR_CANCELED' || error.name === 'CanceledError') {
      return Promise.reject({ code: -1, msg: 'canceled', canceled: true })
    }
    const status = error.response?.status
    const data = error.response?.data
    const msg = data?.msg || error.message || '网络异常'

    if (status === 401) {
      localStorage.removeItem('zhy_token')
      if (!location.pathname.startsWith('/login') && !location.pathname.startsWith('/share/')) {
        location.href = '/login'
      }
      // 登录页自身的 401（如密码错误）也需要提示
      if (!error.config?.silent) {
        ElMessage.error(msg)
      }
    } else if (!error.config?.silent) {
      ElMessage.error(msg)
    }
    return Promise.reject(data || { code: status || -1, msg })
  },
)

export default service
