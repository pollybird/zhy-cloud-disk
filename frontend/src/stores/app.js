import { defineStore } from 'pinia'
import { getStatus } from '../api/setup'
import { getFeatureFlags } from '../api/system'

export const useAppStore = defineStore('app', {
  state: () => ({
    installed: null,
    version: '',
    statusLoaded: false,
    // 1.1.0 功能开关：null=未加载，true/false=已加载
    departmentDrive: null,
    // 1.3.0 回收站 / 历史版本开关
    trashEnabled: null,
    versionEnabled: null,
  }),
  actions: {
    async fetchStatus() {
      try {
        const res = await getStatus()
        this.installed = res.data.installed
        this.version = res.data.version
      } catch (e) {
        this.installed = null
      } finally {
        this.statusLoaded = true
      }
    },
    async fetchFeatureFlags() {
      try {
        const res = await getFeatureFlags()
        this.departmentDrive = !!res.data.department_drive
        this.trashEnabled = res.data.trash_enabled !== false
        this.versionEnabled = res.data.version_enabled !== false
      } catch (e) {
        this.departmentDrive = false
        this.trashEnabled = true
        this.versionEnabled = true
      }
      return this.departmentDrive
    },
  },
})
