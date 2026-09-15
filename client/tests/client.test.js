/**
 * client.test.js — axios 封装：响应解包 / 流透传 / 401 自动刷新 / 请求注入
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import axios from 'axios'

vi.mock('axios', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, default: { ...actual.default, post: vi.fn() } }
})

import http, { setCredentials, setOnAuthExpired, getServerUrl, getAccessToken } from '../src/lib/api/client.js'

const reqHandler = http.interceptors.request.handlers[0]
const resHandler = http.interceptors.response.handlers[0]

beforeEach(() => {
  vi.clearAllMocks()
  setCredentials('http://mock-server', 'ACCESS_OLD', 'REFRESH')
  setOnAuthExpired(null)
  http.defaults.adapter = vi.fn(async (config) => ({
    data: { code: 0, msg: 'ok', data: { echoed: config.url } },
    status: 200,
    statusText: 'OK',
    headers: {},
    config,
  }))
})

describe('setCredentials', () => {
  it('去除 serverUrl 末尾斜杠', () => {
    setCredentials('http://srv/', 'A', 'R')
    expect(getServerUrl()).toBe('http://srv')
  })
})

describe('请求拦截器', () => {
  it('注入 baseURL 与 Bearer token', () => {
    const config = reqHandler.fulfilled({ headers: {} })
    expect(config.baseURL).toBe('http://mock-server')
    expect(config.headers.Authorization).toBe('Bearer ACCESS_OLD')
  })

  it('无 token 时不注入 Authorization', () => {
    setCredentials('http://mock-server', null, null)
    const config = reqHandler.fulfilled({ headers: {} })
    expect(config.headers.Authorization).toBeUndefined()
  })
})

describe('响应拦截器', () => {
  it('code=0 → 返回完整 body', () => {
    const body = { code: 0, msg: 'ok', data: { v: 1 } }
    expect(resHandler.fulfilled({ data: body, config: {} })).toBe(body)
  })

  it('code!=0 → 抛出携带 code 的错误', async () => {
    const res = { data: { code: 3103, msg: '同名冲突', data: null }, config: {} }
    await expect(
      Promise.resolve().then(() => resHandler.fulfilled(res))
    ).rejects.toMatchObject({ code: 3103, message: '同名冲突' })
  })

  it('stream/blob 响应 → 原样透传（不解包）', () => {
    const res = { data: {}, config: { responseType: 'stream' } }
    expect(resHandler.fulfilled(res)).toBe(res)
  })

  it('非标准 body → 原样返回', () => {
    const res = { data: 'plain', config: {} }
    expect(resHandler.fulfilled(res)).toBe('plain')
  })
})

describe('401 自动刷新', () => {
  function make401Error() {
    return {
      response: { status: 401 },
      config: { url: '/api/file/list', headers: { Authorization: 'Bearer ACCESS_OLD' } },
    }
  }

  it('刷新成功 → 更新 token 并重试原请求', async () => {
    axios.post.mockResolvedValue({
      data: { code: 0, data: { access_token: 'ACCESS_NEW', refresh_token: 'REFRESH_NEW' } },
    })
    const result = await resHandler.rejected(make401Error())
    expect(axios.post).toHaveBeenCalledWith(
      'http://mock-server/api/auth/refresh',
      null,
      expect.objectContaining({ headers: { Authorization: 'Bearer REFRESH' } })
    )
    expect(getAccessToken()).toBe('ACCESS_NEW')
    // 重试请求返回了解包后的 body
    expect(result).toEqual({ code: 0, msg: 'ok', data: expect.anything() })
  })

  it('刷新失败 → 触发 onAuthExpired 并抛出原错误', async () => {
    axios.post.mockRejectedValue(new Error('refresh fail'))
    const onExpired = vi.fn()
    setOnAuthExpired(onExpired)
    await expect(resHandler.rejected(make401Error())).rejects.toMatchObject({ response: { status: 401 } })
    expect(onExpired).toHaveBeenCalled()
  })

  it('无 refreshToken → 不尝试刷新，触发 onAuthExpired', async () => {
    setCredentials('http://mock-server', 'ACCESS_OLD', null)
    const onExpired = vi.fn()
    setOnAuthExpired(onExpired)
    await expect(resHandler.rejected(make401Error())).rejects.toMatchObject({ response: { status: 401 } })
    expect(axios.post).not.toHaveBeenCalled()
    expect(onExpired).toHaveBeenCalled()
  })

  it('非 401 错误 → 不刷新直接抛出', async () => {
    const err = { response: { status: 500 }, config: { headers: {} } }
    await expect(resHandler.rejected(err)).rejects.toBe(err)
    expect(axios.post).not.toHaveBeenCalled()
  })
})
