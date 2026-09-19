<template>
  <el-dialog
    :model-value="modelValue"
    :title="`历史版本 — ${node?.file_name || ''}`"
    width="680px"
    @update:model-value="(v) => emit('update:modelValue', v)"
    @open="load"
  >
    <div v-if="current" class="current-bar">
      <el-tag size="small" type="success" effect="plain">当前版本</el-tag>
      <span class="current-meta">
        {{ formatSize(current.file_size) }} · 更新于 {{ formatTime(current.upload_time) }}
      </span>
    </div>

    <el-table :data="items" v-loading="loading" size="small" height="320" empty-text="暂无历史版本">
      <el-table-column label="版本" width="80">
        <template #default="{ row }">
          <el-tag size="small" effect="plain">v{{ row.version_no }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="大小" width="100">
        <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
      </el-table-column>
      <el-table-column label="修改人" width="120" show-overflow-tooltip>
        <template #default="{ row }">{{ row.operator_name || '—' }}</template>
      </el-table-column>
      <el-table-column label="保存时间" width="170">
        <template #default="{ row }">{{ formatTime(row.create_time) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" :disabled="busy" @click="downloadRow(row)">下载</el-button>
          <el-button link type="warning" :disabled="busy" @click="restoreRow(row)">恢复</el-button>
        </template>
      </el-table-column>
    </el-table>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

const props = defineProps({
  modelValue: Boolean,
  node: { type: Object, default: null }, // 文件节点（非文件夹）
})
const emit = defineEmits(['update:modelValue', 'restored'])

const loading = ref(false)
const busy = ref(false)
const items = ref([])
const current = ref(null)

function formatSize(n) {
  if (n == null) return '-'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = Number(n)
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}
function formatTime(t) {
  return t ? new Date(t).toLocaleString('zh-CN', { hour12: false }) : '—'
}

async function unwrap(promise) {
  const res = await promise
  if (!res.success) throw new Error(res.error || '操作失败')
  return res.data
}

async function load() {
  if (!props.node?.id) return
  loading.value = true
  try {
    const data = await unwrap(window.zhy.versions.list(props.node.id))
    items.value = data.items || []
    current.value = data.current || null
  } catch (e) {
    items.value = []
    current.value = null
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

async function downloadRow(row) {
  busy.value = true
  try {
    const data = await unwrap(
      window.zhy.versions.download(row.id, `${props.node.file_name}.v${row.version_no}`)
    )
    if (!data.canceled) {
      ElMessage.success(`已保存到「${data.filePath}」`)
    }
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    busy.value = false
  }
}

async function restoreRow(row) {
  try {
    await ElMessageBox.confirm(
      `恢复到 v${row.version_no}？当前内容将另存为新版本，可随时切换回来。`,
      '恢复历史版本',
      { confirmButtonText: '恢复', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  busy.value = true
  try {
    await unwrap(window.zhy.versions.restore(row.id))
    ElMessage.success(`已恢复到 v${row.version_no}`)
    await load()
    emit('restored')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    busy.value = false
  }
}

watch(
  () => props.node?.id,
  () => {
    if (props.modelValue) load()
  }
)
</script>

<style scoped>
.current-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.current-meta {
  font-size: 12px;
  color: #909399;
}
</style>
