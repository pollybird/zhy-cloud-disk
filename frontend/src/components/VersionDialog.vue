<template>
  <el-dialog
    :model-value="modelValue"
    title="历史版本"
    width="640px"
    :close-on-click-modal="false"
    @update:model-value="(v) => emit('update:modelValue', v)"
    @open="load"
  >
    <div v-if="node?.file_name" class="file-title">
      <FileIcon class="file-icon" :row="node" :size="18" />
      <span>{{ node.file_name }}</span>
    </div>

    <el-table :data="items" v-loading="loading" size="small" border stripe>
      <el-table-column prop="version_no" label="版本" width="70" />
      <el-table-column label="大小" width="100">
        <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
      </el-table-column>
      <el-table-column label="修改人" width="110">
        <template #default="{ row }">{{ row.operator_name || '-' }}</template>
      </el-table-column>
      <el-table-column label="时间" min-width="160">
        <template #default="{ row }">{{ formatDateTime(row.create_time) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="onDownload(row)">
            下载
          </el-button>
          <el-button link type="warning" size="small" @click="onRestore(row)">
            恢复
          </el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="暂无历史版本" :image-size="80" />
      </template>
    </el-table>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import FileIcon from './FileIcon.vue'
import { downloadVersion, listVersions, restoreVersion } from '../api/version'
import { formatDateTime, formatSize } from '../utils/format'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  node: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['restored'])

const items = ref([])
const loading = ref(false)

async function load() {
  if (!props.node?.id) return
  loading.value = true
  try {
    const res = await listVersions(props.node.id)
    items.value = res.data.items || []
  } finally {
    loading.value = false
  }
}

async function onDownload(row) {
  const response = await downloadVersion(row.id)
  const disposition = response.headers['content-disposition'] || ''
  let name = `${props.node.file_name || 'file'}.v${row.version_no}`
  const star = /filename\*=UTF-8''(.+)$/i.exec(disposition)
  if (star) {
    name = decodeURIComponent(star[1])
  } else {
    const plain = /filename="?([^";]+)"?/i.exec(disposition)
    if (plain) name = plain[1]
  }
  const url = URL.createObjectURL(response.data)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

async function onRestore(row) {
  await ElMessageBox.confirm(
    `恢复后当前文件内容将被替换为 v${row.version} 版本（当前内容会自动存入历史版本），确认恢复？`,
    '恢复版本',
    { type: 'warning', confirmButtonText: '恢复', cancelButtonText: '取消' },
  )
  await restoreVersion(row.id)
  ElMessage.success('版本已恢复')
  emit('restored')
  emit('update:modelValue', false)
}
</script>

<style scoped>
.file-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-weight: 600;
  color: #1e293b;
}

.file-icon {
  font-size: 16px;
}
</style>
