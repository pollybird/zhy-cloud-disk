<template>
  <el-drawer
    :model-value="modelValue"
    :title="scope === 'department' ? '部门回收站' : '回收站'"
    size="560px"
    @update:model-value="(v) => emit('update:modelValue', v)"
    @open="load"
  >
    <div class="trash-head">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="删除的文件会保留到到期时间，到期后自动彻底删除；清空回收站将立即释放存储空间。"
      />
      <el-button
        type="danger"
        plain
        :disabled="!items.length"
        :loading="emptying"
        style="margin-top: 10px"
        @click="onEmpty"
      >
        清空回收站
      </el-button>
    </div>

    <el-table :data="items" v-loading="loading" size="small" style="margin-top: 12px">
      <el-table-column label="名称" min-width="180">
        <template #default="{ row }">
          <div class="name-line">
            <FileIcon class="file-icon" :row="row" :size="18" />
            <span>{{ row.file_name }}</span>
            <el-tag v-if="row.is_folder" size="small" type="warning" effect="plain">
              文件夹
            </el-tag>
          </div>
          <div v-if="scope === 'department' && row.operator_name" class="sub">
            删除人：{{ row.operator_name }}
          </div>
        </template>
      </el-table-column>
      <el-table-column label="大小" width="80">
        <template #default="{ row }">
          {{ row.is_folder ? '-' : formatSize(row.file_size) }}
        </template>
      </el-table-column>
      <el-table-column label="到期时间" width="110">
        <template #default="{ row }">
          <span class="expire">{{ formatDate(row.expire_time) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="130" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="onRestore(row)">
            还原
          </el-button>
          <el-button link type="danger" size="small" @click="onPurge(row)">
            彻底删除
          </el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="回收站为空" :image-size="80" />
      </template>
    </el-table>
  </el-drawer>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import FileIcon from './FileIcon.vue'
import { emptyTrash, listTrash, purgeTrashItem, restoreTrash } from '../api/trash'
import { formatDateTime, formatSize } from '../utils/format'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  scope: { type: String, default: 'personal' }, // personal | department
  departmentId: { type: [Number, String], default: null },
})
const emit = defineEmits(['update:modelValue', 'changed'])

const items = ref([])
const loading = ref(false)
const emptying = ref(false)

function formatDate(iso) {
  if (!iso) return '-'
  return formatDateTime(iso).slice(0, 10)
}

async function load() {
  loading.value = true
  try {
    const params = { scope: props.scope }
    if (props.scope === 'department' && props.departmentId) {
      params.department_id = props.departmentId
    }
    const res = await listTrash(params)
    items.value = res.data.items || []
  } finally {
    loading.value = false
  }
}

async function onRestore(row) {
  await restoreTrash(row.id)
  ElMessage.success('已还原')
  items.value = items.value.filter((it) => it.id !== row.id)
  emit('changed')
}

async function onPurge(row) {
  await ElMessageBox.confirm(
    `「${row.file_name}」将被彻底删除，无法恢复，确认继续？`,
    '彻底删除',
    { type: 'warning', confirmButtonText: '彻底删除', cancelButtonText: '取消' },
  )
  await purgeTrashItem(row.id)
  ElMessage.success('已彻底删除')
  items.value = items.value.filter((it) => it.id !== row.id)
  emit('changed')
}

async function onEmpty() {
  await ElMessageBox.confirm(
    '将彻底删除回收站内全部内容，且无法恢复，确认继续？',
    '清空回收站',
    { type: 'error', confirmButtonText: '全部删除', cancelButtonText: '取消' },
  )
  emptying.value = true
  try {
    const params = { scope: props.scope }
    if (props.scope === 'department' && props.departmentId) {
      params.department_id = props.departmentId
    }
    await emptyTrash(params)
    ElMessage.success('回收站已清空')
    items.value = []
    emit('changed')
  } finally {
    emptying.value = false
  }
}
</script>

<style scoped>
.trash-head {
  padding: 0 2px;
}

.name-line {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.file-icon {
  font-size: 16px;
}

.sub,
.expire {
  font-size: 12px;
  color: #94a3b8;
}
</style>
