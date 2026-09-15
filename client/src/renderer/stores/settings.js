import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useSettingsStore = defineStore('settings', () => {
  const serverUrl = ref('')
  const username = ref('')
  const syncPath = ref('')
  const autoStart = ref(false)
  const pollInterval = ref(60)
  const conflictStrategy = ref('keep-both')
  const configured = ref(false)
  const syncState = ref('idle')

  async function loadSettings() {
    const s = await window.zhy.getSettings()
    serverUrl.value = s.serverUrl || ''
    username.value = s.username || ''
    syncPath.value = s.syncPath || ''
    autoStart.value = s.autoStart || false
    pollInterval.value = s.pollInterval || 60
    conflictStrategy.value = s.conflictStrategy || 'keep-both'
    configured.value = s.configured || false
  }

  async function saveSettings(updates) {
    const s = await window.zhy.setSettings(updates)
    if (updates.serverUrl !== undefined) serverUrl.value = updates.serverUrl
    if (updates.syncPath !== undefined) syncPath.value = updates.syncPath
    if (updates.autoStart !== undefined) autoStart.value = updates.autoStart
    if (updates.pollInterval !== undefined) pollInterval.value = updates.pollInterval
    if (updates.conflictStrategy !== undefined) conflictStrategy.value = updates.conflictStrategy
    if (updates.configured !== undefined) configured.value = updates.configured
    return s
  }

  async function updateSyncState() {
    const s = await window.zhy.getSyncStatus()
    syncState.value = s.state
  }

  return {
    serverUrl, username, syncPath, autoStart, pollInterval, conflictStrategy,
    configured, syncState,
    loadSettings, saveSettings, updateSyncState,
  }
})
