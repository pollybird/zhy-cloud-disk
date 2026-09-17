import { defineStore } from 'pinia'
import {
  login as loginApi,
  logout as logoutApi,
  register as registerApi,
} from '../api/auth'
import { getUserInfo } from '../api/user'
import { getMyAdminDepts } from '../api/permission'

export const useUserStore = defineStore('user', {
  state: () => ({
    token: localStorage.getItem('zhy_token') || '',
    refreshToken: localStorage.getItem('zhy_refresh_token') || '',
    user: null,
    // 1.1.0 当前用户被委派的部门管理员列表 [{department_id, scope}]
    adminDepts: [],
    adminDeptsLoaded: false,
  }),
  getters: {
    isLogin: (state) => !!state.token,
    isAdmin: (state) => state.user?.role === 'admin',
    // 是否具有部门管理入口（超管或任一部门管理员）
    canManageDrive(state) {
      return state.user?.role === 'admin' || state.adminDepts.length > 0
    },
  },
  actions: {
    setTokens(access_token, refresh_token) {
      this.token = access_token
      this.refreshToken = refresh_token || ''
      localStorage.setItem('zhy_token', access_token)
      if (refresh_token) {
        localStorage.setItem('zhy_refresh_token', refresh_token)
      }
    },
    async login(username, password) {
      const res = await loginApi(username, password)
      this.setTokens(res.data.access_token, res.data.refresh_token)
      this.user = res.data.user
      return res.data.user
    },
    async register(username, email, password) {
      return registerApi(username, email, password)
    },
    async fetchInfo() {
      const res = await getUserInfo()
      this.user = res.data.user
      return this.user
    },
    async fetchAdminDepts() {
      try {
        const res = await getMyAdminDepts()
        this.adminDepts = res.data || []
      } catch (e) {
        this.adminDepts = []
      } finally {
        this.adminDeptsLoaded = true
      }
      return this.adminDepts
    },
    async logout() {
      try {
        await logoutApi()
      } catch (e) {
        // 忽略服务端错误，本地必须清理
      }
      this.clear()
    },
    clear() {
      this.token = ''
      this.refreshToken = ''
      this.user = null
      localStorage.removeItem('zhy_token')
      localStorage.removeItem('zhy_refresh_token')
    },
  },
})
