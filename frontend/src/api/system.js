import request from './request'

export function getFeatureFlags() {
  return request({ url: '/api/system/feature-flags', method: 'get', silent: true })
}
