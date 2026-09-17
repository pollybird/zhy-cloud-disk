<template>
  <el-card>
    <template #header>
      <div class="card-header">
        <span>部门成员管理</span>
        <div class="tools">
          <el-tree-select
            v-model="deptId"
            :data="deptOptions"
            check-strictly
            :render-after-expand="false"
            default-expand-all
            placeholder="选择部门"
            style="width: 260px"
            @change="loadMembers"
          />
          <el-button type="primary" :disabled="!deptId" @click="openAdd">
            <el-icon><Plus /></el-icon>&nbsp;添加成员
          </el-button>
        </div>
      </div>
    </template>

    <el-empty v-if="!deptId" description="请先选择部门" />
    <template v-else>
      <el-table :data="members" v-loading="loading" border stripe>
        <el-table-column prop="username" label="用户名" min-width="120" />
        <el-table-column prop="email" label="邮箱" min-width="180" />
        <el-table-column prop="position" label="职位" min-width="120">
          <template #default="{ row }">{{ row.position || '-' }}</template>
        </el-table-column>
        <el-table-column label="账号状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'warning'" size="small">
              {{ row.status === 'active' ? '正常' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="加入时间" width="165">
          <template #default="{ row }">{{ formatDateTime(row.join_time) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">调整职位</el-button>
            <el-button link type="danger" @click="handleRemove(row)">移除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </template>

    <!-- 添加成员 -->
    <el-dialog v-model="addVisible" title="添加成员" width="480px" :close-on-click-modal="false">
      <el-form label-width="90px">
        <el-form-item label="搜索用户">
          <el-input
            v-model="keyword"
            placeholder="用户名 / 邮箱关键字"
            clearable
            @input="searchCandidates"
          />
        </el-form-item>
        <el-form-item label="选择用户">
          <el-select
            v-model="addForm.user_id"
            filterable
            remote
            :remote-method="searchCandidates"
            :loading="candidatesLoading"
            placeholder="输入关键字搜索用户"
            style="width: 100%"
          >
            <el-option
              v-for="u in candidates"
              :key="u.id"
              :label="`${u.username}（${u.email}）`"
              :value="u.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="职位">
          <el-input v-model="addForm.position" maxlength="64" placeholder="如：部长 / 员工（可留空）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleAdd">添加</el-button>
      </template>
    </el-dialog>

    <!-- 调整职位 -->
    <el-dialog v-model="editVisible" :title="`调整职位：${editing?.username}`" width="420px">
      <el-form label-width="90px">
        <el-form-item label="职位">
          <el-input v-model="editPosition" maxlength="64" placeholder="职位名称" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleEdit">保存</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute } from 'vue-router'
import {
  addMember,
  getCandidateUsers,
  getDepartmentTree,
  getMembers,
  removeMember,
  updateMember,
} from '../../api/department'
import { formatDateTime } from '../../utils/format'

const route = useRoute()

const deptId = ref(null)
const treeData = ref([])
const members = ref([])
const loading = ref(false)
const saving = ref(false)

const deptOptions = computed(() => treeData.value)

const addVisible = ref(false)
const keyword = ref('')
const candidates = ref([])
const candidatesLoading = ref(false)
const addForm = ref({ user_id: null, position: '' })

const editVisible = ref(false)
const editing = ref(null)
const editPosition = ref('')

async function loadTree() {
  const res = await getDepartmentTree()
  treeData.value = res.data || []
}

async function loadMembers() {
  if (!deptId.value) return
  loading.value = true
  try {
    const res = await getMembers(deptId.value)
    members.value = res.data || []
  } catch (e) {
    members.value = []
  } finally {
    loading.value = false
  }
}

async function searchCandidates(query) {
  if (!deptId.value) return
  candidatesLoading.value = true
  try {
    const res = await getCandidateUsers(deptId.value, query || '')
    candidates.value = res.data || []
  } catch (e) {
    candidates.value = []
  } finally {
    candidatesLoading.value = false
  }
}

function openAdd() {
  addForm.value = { user_id: null, position: '' }
  keyword.value = ''
  candidates.value = []
  addVisible.value = true
  searchCandidates('')
}

async function handleAdd() {
  if (!addForm.value.user_id) {
    ElMessage.warning('请选择要添加的用户')
    return
  }
  saving.value = true
  try {
    await addMember(deptId.value, {
      user_id: addForm.value.user_id,
      position: addForm.value.position.trim(),
    })
    ElMessage.success('成员添加成功')
    addVisible.value = false
    await loadMembers()
  } finally {
    saving.value = false
  }
}

function openEdit(row) {
  editing.value = row
  editPosition.value = row.position || ''
  editVisible.value = true
}

async function handleEdit() {
  saving.value = true
  try {
    await updateMember(deptId.value, editing.value.user_id, { position: editPosition.value.trim() })
    ElMessage.success('职位更新成功')
    editVisible.value = false
    await loadMembers()
  } finally {
    saving.value = false
  }
}

async function handleRemove(row) {
  await ElMessageBox.confirm(
    `确定将用户「${row.username}」移出本部门吗？移除后其部门文件权限（默认只读）随之失效。`,
    '移除确认',
    { type: 'warning', confirmButtonText: '移除', cancelButtonText: '取消' },
  )
  await removeMember(deptId.value, row.user_id)
  ElMessage.success('成员移除成功')
  await loadMembers()
}

onMounted(async () => {
  await loadTree()
  const initial = Number(route.query.dept_id)
  if (initial) {
    deptId.value = initial
    await loadMembers()
  }
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
</style>
