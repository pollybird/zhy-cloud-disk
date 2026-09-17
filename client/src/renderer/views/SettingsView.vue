<template>
  <div class="settings-container">
    <el-card shadow="always" class="settings-card">
      <template #header>
        <div class="settings-header">
          <div class="header-left">
            <el-button link @click="router.push('/')">
              <el-icon><ArrowLeft /></el-icon>&nbsp;返回
            </el-button>
            <span>钟毓云盘设置</span>
          </div>
          <el-tag :type="statusType" size="small">{{ statusText }}</el-tag>
        </div>
      </template>

      <el-form label-position="top" :model="form">
        <el-divider content-position="left">服务器</el-divider>
        <el-form-item label="服务器地址">
          <el-input v-model="form.serverUrl" disabled />
        </el-form-item>
        <el-form-item label="账号">
          <el-input v-model="form.username" disabled />
        </el-form-item>

        <el-divider content-position="left">同步</el-divider>
        <el-form-item label="同步文件夹">
          <el-input v-model="form.syncPath" readonly>
            <template #append>
              <el-button @click="changeFolder">
                <el-icon><FolderOpened /></el-icon>
              </el-button>
            </template>
          </el-input>
        </el-form-item>
        <el-form-item label="轮询间隔（秒）">
          <el-input-number v-model="form.pollInterval" :min="10" :max="600" :step="10" />
        </el-form-item>
        <el-form-item label="冲突策略">
          <el-select v-model="form.conflictStrategy" style="width: 200px">
            <el-option label="保留两者" value="keep-both" />
            <el-option label="最后修改者胜出" value="last-write-wins" />
          </el-select>
        </el-form-item>

        <el-divider content-position="left">开机</el-divider>
        <el-form-item>
          <el-switch v-model="form.autoStart" active-text="开机自启" />
        </el-form-item>
      </el-form>

      <div class="actions">
        <el-button type="primary" @click="save">保存设置</el-button>
        <el-button v-if="syncPaused" type="success" @click="resumeSync">恢复同步</el-button>
        <el-button v-else type="warning" @click="pauseSync">暂停同步</el-button>
        <el-button type="danger" plain @click="doLogout">退出登录</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { FolderOpened, ArrowLeft } from '@element-plus/icons-vue'
import { useSettingsStore } from '../stores/settings.js'

const router = useRouter()
const store = useSettingsStore()

const form = ref({
  serverUrl: '',
  username: '',
  syncPath: '',
  autoStart: false,
  pollInterval: 60,
  conflictStrategy: 'keep-both',
})

const syncState = ref('idle')
const syncPaused = computed(() => syncState.value === 'paused')

const statusText = computed(() => {
  const map = {
    idle: '已同步',
    'first-sync': '首次同步中',
    syncing: '同步中',
    paused: '已暂停',
    error: '错误',
  }
  return map[syncState.value] || syncState.value
})

const statusType = computed(() => {
  const map = {
    idle: 'success',
    'first-sync': 'warning',
    syncing: 'primary',
    paused: 'info',
    error: 'danger',
  }
  return map[syncState.value] || 'info'
})

onMounted(async () => {
  await loadSettings()
})

async function loadSettings() {
  const s = await window.zhy.getSettings()
  form.value.serverUrl = s.serverUrl || ''
  form.value.username = s.username || ''
  form.value.syncPath = s.syncPath || ''
  form.value.autoStart = s.autoStart || false
  form.value.pollInterval = s.pollInterval || 60
  form.value.conflictStrategy = s.conflictStrategy || 'keep-both'
  const st = await window.zhy.getSyncStatus()
  syncState.value = st.state
}

async function changeFolder() {
  const dir = await window.zhy.chooseFolder()
  if (dir) form.value.syncPath = dir
}

async function save() {
  await store.saveSettings({
    syncPath: form.value.syncPath,
    autoStart: form.value.autoStart,
    pollInterval: form.value.pollInterval,
    conflictStrategy: form.value.conflictStrategy,
  })
  await window.zhy.setAutoStart(form.value.autoStart)
  ElMessage.success('设置已保存')
}

async function pauseSync() {
  await window.zhy.pauseSync()
  syncState.value = 'paused'
}

async function resumeSync() {
  await window.zhy.resumeSync()
  syncState.value = 'idle'
}

async function doLogout() {
  try {
    await ElMessageBox.confirm('确定退出登录？同步将停止。', '提示', { type: 'warning' })
    await window.zhy.logout()
    ElMessage.success('已退出登录')
    router.push('/')
  } catch {
    // 取消
  }
}
</script>

<style scoped>
.settings-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f7fa;
  padding: 20px;
}
.settings-card {
  width: 100%;
  max-width: 600px;
}
.settings-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.actions {
  display: flex;
  gap: 12px;
  margin-top: 16px;
}
</style>
