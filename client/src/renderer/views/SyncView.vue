<template>
  <div class="sync-container">
    <el-card shadow="always" class="sync-card">
      <template #header>
        <div class="header">
          <div class="header-left">
            <span class="title">钟毓云盘</span>
            <el-tag :type="stateType[state]" size="small">{{ stateText[state] || state }}</el-tag>
          </div>
          <div class="header-btns">
            <el-button size="small" @click="openFolder">
              <el-icon><FolderOpened /></el-icon>&nbsp;打开文件夹
            </el-button>
            <el-button size="small" type="primary" plain @click="syncNow" :disabled="state === 'first-sync'">
              <el-icon><Refresh /></el-icon>&nbsp;立即同步
            </el-button>
            <el-button size="small" @click="router.push('/settings')">
              <el-icon><Setting /></el-icon>&nbsp;设置
            </el-button>
          </div>
        </div>
      </template>

      <el-tabs v-model="tab" @tab-change="loadLogs">
        <el-tab-pane label="全部记录" name="all" />
        <el-tab-pane :label="`已同步 (${countSynced})`" name="success" />
        <el-tab-pane :label="`失败 (${countFailed})`" name="failed" />
      </el-tabs>

      <el-table
        :data="logs"
        size="small"
        height="360"
        v-loading="loading"
        :empty-text="loading ? '加载中...' : '暂无同步记录'"
      >
        <el-table-column label="时间" width="105">
          <template #default="{ row }">{{ fmtTime(row.ts) }}</template>
        </el-table-column>
        <el-table-column label="类型" width="70" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="actionStyle[row.action] || 'info'">
              {{ actionText[row.action] || row.action }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="file_name" label="文件" show-overflow-tooltip>
          <template #default="{ row }">{{ row.file_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="80" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="statusStyle[row.status] || 'info'">
              {{ statusText[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="message" label="说明" show-overflow-tooltip>
          <template #default="{ row }">{{ row.message || '—' }}</template>
        </el-table-column>
      </el-table>

      <div class="footer">
        <span class="hint">关闭窗口后将驻留系统托盘，右键托盘图标可退出</span>
        <el-button link type="danger" size="small" @click="clearLogs">清空记录</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { FolderOpened, Refresh, Setting } from '@element-plus/icons-vue'

const router = useRouter()

const state = ref('idle')
const tab = ref('all')
const logs = ref([])
const loading = ref(false)
const countSynced = ref(0)
const countFailed = ref(0)

const stateText = {
  idle: '已同步',
  'first-sync': '首次同步中',
  syncing: '同步中',
  paused: '已暂停',
  error: '同步错误',
}
const stateType = {
  idle: 'success',
  'first-sync': 'warning',
  syncing: 'primary',
  paused: 'info',
  error: 'danger',
}
const actionText = {
  download: '下载',
  upload: '上传',
  delete: '删除',
  rename: '改名',
  move: '移动',
  mkdir: '建目录',
}
const actionStyle = {
  download: 'primary',
  upload: 'success',
  delete: 'danger',
  rename: 'warning',
  move: 'warning',
  mkdir: 'warning',
}
const statusText = {
  success: '成功',
  failed: '失败',
  skipped: '已跳过',
}
const statusStyle = {
  success: 'success',
  failed: 'danger',
  skipped: 'info',
}

function fmtTime(ts) {
  if (!ts) return ''
  return new Date(ts).toLocaleString('zh-CN', { hour12: false })
}

async function loadLogs() {
  loading.value = true
  try {
    const statusFilter = tab.value === 'all' ? undefined : tab.value
    const res = await window.zhy.getSyncLogs({ status: statusFilter, limit: 200 })
    logs.value = res.rows || []
  } finally {
    loading.value = false
  }
  countSynced.value = await window.zhy.getSyncLogs({ status: 'success', limit: 1 }).then((r) => r.total)
  countFailed.value = await window.zhy.getSyncLogs({ status: 'failed', limit: 1 }).then((r) => r.total)
}

async function refreshState() {
  const res = await window.zhy.getSyncStatus()
  state.value = res.state
}

function openFolder() {
  window.zhy.openSyncFolder()
}

function syncNow() {
  window.zhy.syncNow()
}

async function clearLogs() {
  try {
    await ElMessageBox.confirm('确定清空全部同步记录？', '提示', {
      confirmButtonText: '清空',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  await window.zhy.clearSyncLogs()
  ElMessage.success('已清空')
  loadLogs()
}

// 日志实时刷新（500ms 去抖）
let logTimer = null
const unsubs = []
onMounted(async () => {
  await refreshState()
  await loadLogs()
  unsubs.push(
    window.zhy.on('sync:state', (s) => {
      state.value = s
      if (s === 'idle') loadLogs()
    }),
    window.zhy.on('sync:log', () => {
      clearTimeout(logTimer)
      logTimer = setTimeout(loadLogs, 500)
    })
  )
})
onUnmounted(() => {
  unsubs.forEach((u) => u && u())
  clearTimeout(logTimer)
})
</script>

<style scoped>
.sync-container {
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding: 24px 16px;
  min-height: 100vh;
}
.sync-card {
  width: 680px;
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.title {
  font-size: 16px;
  font-weight: 600;
}
.footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 10px;
}
.hint {
  font-size: 12px;
  color: #909399;
}
</style>
