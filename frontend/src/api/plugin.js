import request from './request'

// ---- 管理端 ----

export function listPlugins() {
  return request({ url: '/api/plugin/list', method: 'get' })
}

export function setPluginEnabled(name, enabled) {
  return request({
    url: `/api/plugin/${name}/enabled`,
    method: 'put',
    data: { enabled },
  })
}

export function registerPlugins(name) {
  return request({
    url: '/api/plugin/register',
    method: 'post',
    data: name ? { name } : {},
  })
}

// ---- 通用插件 API ----

export function availablePlugins(suffix) {
  return request({
    url: '/api/plugin/available',
    method: 'get',
    params: { suffix },
  })
}

/** 拉取文件流（blob，带 JWT；用于归属预览） */
export function fetchStream(params) {
  return request({
    url: '/api/plugin/file/stream',
    method: 'get',
    params,
    responseType: 'blob',
    timeout: 0,
    silent: true,
  })
}

/** 分享访客直链（img/video/iframe 可直接引用） */
export function pluginStreamUrl(code, token) {
  return `/api/plugin/file/stream?code=${encodeURIComponent(code)}&token=${encodeURIComponent(token)}`
}

/** 文本编辑保存（重新走配额与类型校验） */
export function saveFileContent(id, content) {
  return request({
    url: '/api/plugin/file/save',
    method: 'post',
    data: { id, content },
  })
}

/** 权限校验（支持归属 id= 或分享 code+token=） */
export function authCheck(params) {
  return request({ url: '/api/plugin/auth/check', method: 'get', params })
}
