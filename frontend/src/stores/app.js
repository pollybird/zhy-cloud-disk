import { defineStore } from 'pinia'
import { getStatus } from '../api/setup'

export const useAppStore = defineStore('app', {
  state: () => ({
    installed: null,
    version: '',
    statusLoaded: false,
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
  },
})
