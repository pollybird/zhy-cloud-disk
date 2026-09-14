import request from './request'

export function getStatus() {
  return request({ url: '/api/setup/status', method: 'get', silent: true })
}

export function getEnvironment(storageDir) {
  return request({
    url: '/api/setup/environment',
    method: 'get',
    params: storageDir ? { storage_dir: storageDir } : {},
  })
}

export function testDatabase(payload) {
  return request({ url: '/api/setup/test-db', method: 'post', data: payload })
}

export function install(payload) {
  return request({ url: '/api/setup/install', method: 'post', data: payload, timeout: 60000 })
}
