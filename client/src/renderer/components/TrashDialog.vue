<template>
  <el-dialog
    :model-value="modelValue"
    :title="scope === 'department' ? '部门回收站' : '个人回收站'"
    width="720px"
    @update:model-value="(v) => emit('update:modelValue', v)"
    @open="load"
  >
    <el-table :data="items" v-loading="loading" size="small" height="360" empty-text="回收站为空">
      <el-table-column label="名称" min-width="220" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="name-cell">
            <FileIcon class="file-icon" :row="row" :size="16" />
            <span>{{ row.file_name }}</span>
          </span>
        </template>
      </el-table-column>
      <el-table-column label="大小" width="90">
        <template #default="{ row }">
          {{ row.is_folder ? '-' : formatSize(row.file_size) }}
        </template>
      </el-table-column>
      <el-table-column label="删除人" width="110" show-overflow-tooltip>
        <template #default="{ row }">{{ row.operator_name || '—' }}</template>
      </el-table-column>
      <el-table-column label="删除时间" width="150">
        <template #default="{ row }">{{ formatTime(row.delete_time) }}</template>
      </el-table-column>
      <el-table-column label="剩余" width="90" align="center">
        <template #default="{ row }">
          <el-tag size="small" :type="remainDays(row) <= 3 ? 'danger' : 'info'" effect="plain">
            {{ remainDays(row) }} 天
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="restoreRow(row)">还原</el-button>
          <el-button link type="danger" @click="purgeRow(row)">彻底删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <template #footer>
      <div class="footer">
        <span class="hint">过期后自动清除，还原后恢复到原位置</span>
        <div>
          <el-button :disabled="!items.length || busy" @click="emptyAll">清空回收站</el-button>
          <el-button type="primary" @click="emit('update:modelValue', false)">关闭</el-button>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import FileIcon from './FileIcon.vue'

const props = defineProps({
  modelValue: Boolean,
  scope: { type: String, default: 'personal' }, // personal | department
  departmentId: { type: Number, default: null },
})
const emit = defineEmits(['update:modelValue', 'changed'])

const loading = ref(false)
const busy = ref(false)
const items = ref([])

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
function remainDays(row) {
  if (!row.expire_time) return '—'
  const d = Math.ceil((new Date(row.expire_time).getTime() - Date.now()) / 86400000)
  return Math.max(d, 0)
}

async function unwrap(promise) {
  const res = await promise
  if (!res.success) throw new Error(res.error || '操作失败')
  return res.data
}

async function load() {
  loading.value = true
  try {
    const data = await unwrap(
      window.zhy.trash.list({ scope: props.scope, departmentId: props.departmentId })
    )
    items.value = data.items || []
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

async function restoreRow(row) {
  busy.value = true
  try {
    await unwrap(window.zhy.trash.restore(row.id))
    ElMessage.success(`已还原「${row.file_name}」`)
    await load()
    emit('changed')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    busy.value = false
  }
}

async function purgeRow(row) {
  try {
    await ElMessageBox.confirm(
      `彻底删除「${row.file_name}」？其历史版本与存储实体将一并清除，不可恢复。`,
      '彻底删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  busy.value = true
  try {
    await unwrap(window.zhy.trash.purge(row.id))
    ElMessage.success('已彻底删除')
    await load()
    emit('changed')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    busy.value = false
  }
}

async function emptyAll() {
  try {
    await ElMessageBox.confirm(
      '清空回收站？全部文件将被彻底删除且不可恢复。',
      '清空回收站',
      { confirmButtonText: '清空', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  busy.value = true
  try {
    const data = await unwrap(
      window.zhy.trash.empty({ scope: props.scope, departmentId: props.departmentId })
    )
    ElMessage.success(`已清空 ${data?.count ?? items.value.length} 项`)
    items.value = []
    emit('changed')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    busy.value = false
  }
}

watch(
  () => [props.scope, props.departmentId],
  () => {
    if (props.modelValue) load()
  }
)
</script>

<style scoped>
.name-cell {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.file-icon {
  font-size: 15px;
}
.footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.hint {
  font-size: 12px;
  color: #909399;
}
</style>
