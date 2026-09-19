<template>
  <el-card v-loading="loading">
    <template #header>
      <div class="card-header">
        <span class="page-title">备份与恢复</span>
        <div class="tools">
          <el-upload
            ref="uploadRef"
            :show-file-list="false"
            :auto-upload="false"
            accept=".zip"
            :on-change="onFilePicked"
          >
            <el-button>
              <el-icon><Upload /></el-icon>&nbsp;上传备份包恢复
            </el-button>
          </el-upload>
          <el-button type="primary" :loading="starting" @click="onCreate">
            <el-icon><VideoPlay /></el-icon>&nbsp;立即备份
          </el-button>
          <el-button circle @click="load"><el-icon><Refresh /></el-icon></el-button>
        </div>
      </div>
    </template>

    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="备份内容为数据库（账号、权限、文件索引等）与系统配置，不包含上传的文件实体；请妥善保留远端账号密码。"
      class="tip"
    />

    <el-table :data="items" border stripe style="margin-top: 12px" :row-class-name="rowClass">
      <el-table-column prop="filename" label="备份文件" min-width="280" show-overflow-tooltip />
      <el-table-column label="类型" width="110">
        <template #default="{ row }">
          <el-tag size="small" effect="plain">{{ dbLabel(row.db_type) }}</el-tag>
          <el-tag
            v-if="row.trigger === 'schedule'"
            size="small"
            type="info"
            effect="plain"
            class="ml6"
          >
            定时
          </el-tag>
          <el-tag v-else size="small" type="success" effect="plain" class="ml6">手动</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="位置" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="row.location === 'remote' ? 'warning' : 'info'" effect="plain">
            {{ row.location === 'remote' ? '远端' : '本地' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="大小" width="100">
        <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="备份时间" width="170">
        <template #default="{ row }">{{ formatDateTime(row.create_time) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button
            link
            type="primary"
            size="small"
            :disabled="row.status === 'running' || !row.exists"
            @click="onDownload(row)"
          >
            下载
          </el-button>
          <el-button
            link
            type="warning"
            size="small"
            :disabled="row.status === 'running' || !row.exists"
            @click="askRestore(row)"
          >
            恢复
          </el-button>
          <el-button
            link
            type="danger"
            size="small"
            :disabled="row.status === 'running'"
            @click="onDelete(row)"
          >
            删除
          </el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="暂无备份，点击右上角「立即备份」开始" :image-size="90" />
      </template>
    </el-table>

    <!-- 恢复确认对话框 -->
    <el-dialog v-model="dialogVisible" title="恢复备份（高危操作）" width="520px">
      <el-alert
        type="error"
        :closable="false"
        show-icon
        title="恢复会用备份包覆盖当前数据库与系统配置，恢复期间产生的数据将丢失；恢复完成后服务自动重启。"
        class="warn"
      />
      <div class="target-line">目标备份：{{ restoreTarget?.filename || restoreTarget?.name || '本地上传的备份包' }}</div>
      <el-checkbox v-model="acknowledged" class="ack">
        我已确认备份包可信，并知悉当前数据将被覆盖
      </el-checkbox>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button
          type="danger"
          :disabled="!acknowledged"
          :loading="restoring"
          @click="confirmRestore"
        >
          确认恢复并重启
        </el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  deleteBackup,
  downloadBackup,
  listBackups,
  restoreBackup,
  restoreBackupUpload,
  startBackup,
} from '../../api/admin'
import { formatDateTime, formatSize } from '../../utils/format'

const items = ref([])
const running = ref(false)
const loading = ref(false)
const starting = ref(false)
let pollTimer = null

const uploadRef = ref()
const dialogVisible = ref(false)
const acknowledged = ref(false)
const restoring = ref(false)
// 待恢复目标：{ kind: 'record', row } | { kind: 'remote', filename } | { kind: 'file', file }
const restoreTarget = ref(null)

function dbLabel(t) {
  if (t === 'mysql') return 'MySQL'
  if (t === 'sqlite') return 'SQLite'
  return t || '未知'
}

function statusType(s) {
  if (s === 'done') return 'success'
  if (s === 'running') return 'warning'
  if (s === 'failed') return 'danger'
  return 'info'
}

function statusLabel(s) {
  return { done: '完成', running: '进行中', failed: '失败' }[s] || s
}

function rowClass({ row }) {
  return row.status === 'failed' ? 'row-failed' : ''
}

async function load() {
  loading.value = true
  try {
    const res = await listBackups()
    items.value = res.data.items || []
    running.value = !!res.data.running
    schedulePoll()
  } catch (e) {
    // 远端不可达时列表接口会整体报错，停止轮询
    running.value = false
  } finally {
    loading.value = false
  }
}

function schedulePoll() {
  if (pollTimer) clearInterval(pollTimer)
  if (running.value) {
    pollTimer = setInterval(async () => {
      try {
        const res = await listBackups()
        items.value = res.data.items || []
        running.value = !!res.data.running
      } catch (e) {
        running.value = false
      }
      if (!running.value && pollTimer) {
        clearInterval(pollTimer)
        pollTimer = null
      }
    }, 3000)
  }
}

async function onCreate() {
  starting.value = true
  try {
    await startBackup()
    ElMessage.success('备份已在后台开始')
    running.value = true
    setTimeout(load, 500)
    schedulePoll()
  } finally {
    starting.value = false
  }
}

async function onDownload(row) {
  let response
  if (row.id) {
    response = await downloadBackup(row.id)
  } else {
    ElMessage.warning('该备份缺少服务端记录，暂不支持在线下载')
    return
  }
  const url = URL.createObjectURL(response.data)
  const a = document.createElement('a')
  a.href = url
  a.download = row.filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

async function onDelete(row) {
  await ElMessageBox.confirm(`确定删除备份「${row.filename}」吗？`, '删除备份', {
    type: 'warning',
    confirmButtonText: '删除',
    cancelButtonText: '取消',
  })
  if (!row.id) {
    ElMessage.warning('该备份缺少服务端记录，请在存储端手动删除')
    return
  }
  await deleteBackup(row.id)
  ElMessage.success('备份已删除')
  load()
}

function askRestore(row) {
  restoreTarget.value = { kind: row.id ? 'record' : 'remote', row }
  acknowledged.value = false
  dialogVisible.value = true
}

function onFilePicked(uploadFile) {
  const file = uploadFile.raw
  if (!file) return
  if (!file.name.toLowerCase().endsWith('.zip')) {
    ElMessage.error('请选择 .zip 备份包')
    uploadRef.value?.clearFiles?.()
    return
  }
  restoreTarget.value = { kind: 'file', file, name: file.name }
  acknowledged.value = false
  dialogVisible.value = true
  uploadRef.value?.clearFiles?.()
}

async function confirmRestore() {
  restoring.value = true
  try {
    const target = restoreTarget.value
    if (target.kind === 'file') {
      await restoreBackupUpload(target.file)
    } else if (target.kind === 'record') {
      await restoreBackup({ backup_id: target.row.id })
    } else {
      await restoreBackup({ remote_filename: target.row.filename })
    }
    dialogVisible.value = false
    ElMessage.success('恢复成功，服务将在约 2 秒后自动重启，如页面无响应请手动刷新')
  } finally {
    restoring.value = false
  }
}

onMounted(load)
onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.page-title {
  font-size: 16px;
  font-weight: 600;
  color: #1e293b;
}

.tools {
  display: flex;
  align-items: center;
  gap: 10px;
}

.tip {
  margin: 0;
}

.ml6 {
  margin-left: 6px;
}

.warn {
  margin-bottom: 14px;
}

.target-line {
  font-size: 13px;
  color: #334155;
  margin-bottom: 12px;
  word-break: break-all;
}

.ack {
  margin-left: 2px;
}

:deep(.row-failed) {
  background-color: #fef2f2;
}
</style>
