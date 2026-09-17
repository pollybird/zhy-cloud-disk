<template>
  <el-card>
    <template #header>
      <div class="card-header">
        <span>操作日志</span>
        <div class="tools">
          <template v-if="userStore.isAdmin">
            <span class="mode-tag">全局日志</span>
          </template>
          <template v-else>
            <el-tree-select
              v-model="deptId"
              :data="deptOptions"
              check-strictly
              :render-after-expand="false"
              default-expand-all
              placeholder="选择管辖部门"
              style="width: 240px"
              @change="reloadFirst"
            />
          </template>
          <el-select
            v-model="action"
            clearable
            placeholder="操作类型"
            style="width: 150px"
            @change="reloadFirst"
          >
            <el-option v-for="(label, key) in actionLabels" :key="key" :label="label" :value="key" />
          </el-select>
          <el-button @click="reloadFirst">查询</el-button>
        </div>
      </div>
    </template>

    <el-table :data="rows" v-loading="loading" border stripe>
      <el-table-column label="时间" width="165">
        <template #default="{ row }">{{ formatDateTime(row.create_time) }}</template>
      </el-table-column>
      <el-table-column prop="username" label="操作人" width="120" />
      <el-table-column label="操作" width="150">
        <template #default="{ row }">
          <el-tag :type="actionTag(row.action)" size="small">
            {{ actionLabels[row.action] || row.action }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="对象" width="110">
        <template #default="{ row }">
          {{ targetLabels[row.target_type] || row.target_type }}
          <span v-if="row.target_id" class="target-id">#{{ row.target_id }}</span>
        </template>
      </el-table-column>
      <el-table-column label="详情" min-width="240">
        <template #default="{ row }">
          <span class="detail">{{ detailText(row.detail) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="IP" width="140">
        <template #default="{ row }">{{ row.ip_address || '-' }}</template>
      </el-table-column>
    </el-table>

    <el-pagination
      class="pager"
      layout="total, prev, pager, next"
      :total="total"
      :page-size="size"
      :current-page="page"
      @current-change="onPageChange"
    />
  </el-card>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { getDepartmentLogs, getGlobalLogs } from '../../api/log'
import { getDepartmentTree } from '../../api/department'
import { useUserStore } from '../../stores/user'
import { formatDateTime } from '../../utils/format'

const userStore = useUserStore()

const deptId = ref(null)
const treeData = ref([])
const action = ref(null)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const loading = ref(false)

const deptOptions = computed(() => treeData.value)

const actionLabels = {
  department_create: '新建部门',
  department_update: '编辑部门',
  department_delete: '删除部门',
  department_move: '迁移部门',
  member_add: '添加成员',
  member_remove: '移除成员',
  member_update: '调整成员',
  admin_grant: '委派管理员',
  admin_revoke: '撤销管理员',
  permission_grant: '授予权限',
  permission_revoke: '撤销权限',
  file_upload: '上传文件',
  file_overwrite: '覆盖文件',
  folder_create: '新建文件夹',
  file_rename: '重命名',
  file_move: '移动',
  file_delete: '删除文件',
}

const actionTags = {
  department_create: 'success',
  department_update: 'primary',
  department_delete: 'danger',
  department_move: 'warning',
  member_add: 'success',
  member_remove: 'danger',
  member_update: 'primary',
  admin_grant: 'danger',
  admin_revoke: 'warning',
  permission_grant: 'success',
  permission_revoke: 'warning',
  file_upload: 'success',
  file_overwrite: 'primary',
  folder_create: 'success',
  file_rename: 'primary',
  file_move: 'primary',
  file_delete: 'danger',
}

const targetLabels = {
  file: '文件',
  folder: '文件夹',
  department: '部门',
  user: '用户',
  permission: '权限',
}

const actionTag = (a) => actionTags[a] || 'info'

function detailText(raw) {
  if (!raw) return '-'
  try {
    const d = JSON.parse(raw)
    return Object.entries(d)
      .filter(([, v]) => v !== null && v !== undefined && v !== '')
      .map(([k, v]) => `${k}: ${v}`)
      .join('，') || '-'
  } catch (e) {
    return raw
  }
}

async function load() {
  loading.value = true
  try {
    const params = {
      page: page.value,
      size: size.value,
      action: action.value || undefined,
    }
    const res = userStore.isAdmin
      ? await getGlobalLogs(params)
      : await getDepartmentLogs(deptId.value, params)
    rows.value = res.data.items || []
    total.value = res.data.total
  } catch (e) {
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function reloadFirst() {
  page.value = 1
  load()
}

function onPageChange(p) {
  page.value = p
  load()
}

onMounted(async () => {
  if (!userStore.isAdmin) {
    const res = await getDepartmentTree()
    treeData.value = res.data || []
  }
  await load()
})
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-header .tools {
  display: flex;
  align-items: center;
  gap: 8px;
}

.mode-tag {
  font-size: 13px;
  color: #64748b;
}

.target-id {
  color: #94a3b8;
  font-size: 12px;
}

.detail {
  font-size: 12px;
  color: #64748b;
  word-break: break-all;
}

.pager {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
