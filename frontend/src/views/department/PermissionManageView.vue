<template>
  <el-card>
    <template #header>
      <div class="card-header">
        <span>权限管理</span>
        <el-tree-select
          v-model="deptId"
          :data="deptOptions"
          check-strictly
          :render-after-expand="false"
          default-expand-all
          placeholder="选择部门"
          style="width: 260px"
          @change="loadAll"
        />
      </div>
    </template>

    <el-empty v-if="!deptId" description="请先选择部门" />
    <el-tabs v-else v-model="activeTab">
      <!-- 管理员委派 -->
      <el-tab-pane label="管理员委派" name="admins">
        <div class="pane-tools">
          <el-button type="primary" :disabled="!canDelegate" @click="openGrantAdmin">
            <el-icon><Plus /></el-icon>&nbsp;委派管理员
          </el-button>
          <span v-if="!canDelegate" class="hint">
            根部门管理员仅超级管理员可委派；子部门需拥有上级部门管理权
          </span>
        </div>
        <el-table :data="admins" v-loading="adminsLoading" border stripe>
          <el-table-column prop="username" label="用户名" min-width="120" />
          <el-table-column prop="email" label="邮箱" min-width="180" />
          <el-table-column label="管辖范围" width="140">
            <template #default="{ row }">
              <el-tag :type="row.scope === 'self_and_sub' ? 'danger' : 'info'" size="small">
                {{ row.scope === 'self_and_sub' ? '本部门及子部门' : '仅本部门' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="委派时间" width="165">
            <template #default="{ row }">{{ formatDateTime(row.granted_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <el-button link type="danger" @click="handleRevokeAdmin(row)">撤销</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 成员权限 -->
      <el-tab-pane label="成员权限" name="perms">
        <div class="pane-tools">
          <el-button type="primary" @click="openGrantPerm">
            <el-icon><Plus /></el-icon>&nbsp;授予权限
          </el-button>
          <span class="hint">权限优先级：禁止访问 &gt; 显式授权 &gt; 成员默认（只读）</span>
        </div>
        <el-table :data="perms" v-loading="permsLoading" border stripe>
          <el-table-column prop="username" label="用户名" min-width="120" />
          <el-table-column label="权限" width="120">
            <template #default="{ row }">
              <el-tag :type="permTag(row.permission)" size="small">
                {{ permLabel(row.permission) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="生效范围" width="140">
            <template #default="{ row }">
              {{ row.folder_id ? `文件夹 #${row.folder_id}` : '整个部门' }}
            </template>
          </el-table-column>
          <el-table-column label="授予时间" width="165">
            <template #default="{ row }">{{ formatDateTime(row.granted_at) }}</template>
          </el-table-column>
          <el-table-column label="过期时间" width="165">
            <template #default="{ row }">
              {{ row.expire_time ? formatDateTime(row.expire_time) : '永久' }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <el-button link type="danger" @click="handleRevokePerm(row)">撤销</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- 委派管理员 -->
    <el-dialog v-model="adminDialogVisible" title="委派管理员" width="480px" :close-on-click-modal="false">
      <el-form label-width="100px">
        <el-form-item label="选择用户">
          <el-select
            v-model="adminForm.user_id"
            filterable
            remote
            :remote-method="searchCandidates"
            :loading="candidatesLoading"
            placeholder="输入用户名 / 邮箱搜索"
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
        <el-form-item label="管辖范围">
          <el-radio-group v-model="adminForm.scope">
            <el-radio value="self_and_sub">本部门及子部门</el-radio>
            <el-radio value="self">仅本部门</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="adminDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleGrantAdmin">确定</el-button>
      </template>
    </el-dialog>

    <!-- 授予权限 -->
    <el-dialog v-model="permDialogVisible" title="授予权限" width="520px" :close-on-click-modal="false">
      <el-form label-width="100px">
        <el-form-item label="选择成员">
          <el-select
            v-model="permForm.user_id"
            filterable
            placeholder="从本部门成员中选择"
            style="width: 100%"
          >
            <el-option
              v-for="m in members"
              :key="m.user_id"
              :label="`${m.username}（${m.email}）`"
              :value="m.user_id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="权限类型">
          <el-radio-group v-model="permForm.permission">
            <el-radio value="read_only">只读</el-radio>
            <el-radio value="read_write">读写</el-radio>
            <el-radio value="denied">禁止访问</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="过期时间">
          <el-date-picker
            v-model="permForm.expire_time"
            type="datetime"
            placeholder="留空表示永久有效"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="permDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleGrantPerm">确定</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute } from 'vue-router'
import { useUserStore } from '../../stores/user'
import { getCandidateUsers, getDepartmentTree, getMembers } from '../../api/department'
import {
  getAdmins,
  getDepartmentPermissions,
  grantAdmin,
  grantPermission,
  revokeAdmin,
  revokePermission,
} from '../../api/permission'
import { formatDateTime } from '../../utils/format'

const route = useRoute()
const userStore = useUserStore()

const deptId = ref(null)
const treeData = ref([])
const activeTab = ref('admins')
const saving = ref(false)

const admins = ref([])
const adminsLoading = ref(false)
const perms = ref([])
const permsLoading = ref(false)
const members = ref([])

const deptOptions = computed(() => treeData.value)

// 根部门管理员仅超管可委派；子部门需上级管理权（前端提示，后端强制）
const canDelegate = computed(() => {
  if (!deptId.value) return false
  if (userStore.isAdmin) return true
  const node = findNode(treeData.value, deptId.value)
  return !!node && node.parent_id != null
})

function findNode(nodes, id) {
  for (const n of nodes) {
    if (n.id === id) return n
    const hit = n.children?.length ? findNode(n.children, id) : null
    if (hit) return hit
  }
  return null
}

const permMap = {
  read_only: { label: '只读', tag: 'info' },
  read_write: { label: '读写', tag: 'success' },
  denied: { label: '禁止访问', tag: 'danger' },
}
const permLabel = (p) => permMap[p]?.label || p
const permTag = (p) => permMap[p]?.tag || 'info'

async function loadAll() {
  if (!deptId.value) return
  await Promise.all([loadAdmins(), loadPerms(), loadMembers()])
}

async function loadAdmins() {
  adminsLoading.value = true
  try {
    const res = await getAdmins(deptId.value)
    admins.value = res.data || []
  } catch (e) {
    admins.value = []
  } finally {
    adminsLoading.value = false
  }
}

async function loadPerms() {
  permsLoading.value = true
  try {
    const res = await getDepartmentPermissions(deptId.value)
    perms.value = res.data || []
  } catch (e) {
    perms.value = []
  } finally {
    permsLoading.value = false
  }
}

async function loadMembers() {
  try {
    const res = await getMembers(deptId.value)
    members.value = res.data || []
  } catch (e) {
    members.value = []
  }
}

// ---------------------------------------------------------------------------
// 管理员委派
// ---------------------------------------------------------------------------

const adminDialogVisible = ref(false)
const adminForm = ref({ user_id: null, scope: 'self_and_sub' })
const candidates = ref([])
const candidatesLoading = ref(false)

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

function openGrantAdmin() {
  adminForm.value = { user_id: null, scope: 'self_and_sub' }
  candidates.value = []
  adminDialogVisible.value = true
  searchCandidates('')
}

async function handleGrantAdmin() {
  if (!adminForm.value.user_id) {
    ElMessage.warning('请选择要委派的用户')
    return
  }
  saving.value = true
  try {
    await grantAdmin({
      department_id: deptId.value,
      user_id: adminForm.value.user_id,
      scope: adminForm.value.scope,
    })
    ElMessage.success('管理员委派成功')
    adminDialogVisible.value = false
    await loadAdmins()
  } finally {
    saving.value = false
  }
}

async function handleRevokeAdmin(row) {
  await ElMessageBox.confirm(
    `确定撤销用户「${row.username}」对本部门的管理员权限吗？`,
    '撤销确认',
    { type: 'warning', confirmButtonText: '撤销', cancelButtonText: '取消' },
  )
  await revokeAdmin(deptId.value, row.user_id)
  ElMessage.success('管理员撤销成功')
  await loadAdmins()
}

// ---------------------------------------------------------------------------
// 成员权限
// ---------------------------------------------------------------------------

const permDialogVisible = ref(false)
const permForm = ref({ user_id: null, permission: 'read_only', expire_time: null })

function openGrantPerm() {
  permForm.value = { user_id: null, permission: 'read_only', expire_time: null }
  permDialogVisible.value = true
}

async function handleGrantPerm() {
  if (!permForm.value.user_id) {
    ElMessage.warning('请选择要授权的成员')
    return
  }
  saving.value = true
  try {
    await grantPermission({
      department_id: deptId.value,
      user_id: permForm.value.user_id,
      permission: permForm.value.permission,
      expire_time: permForm.value.expire_time ? permForm.value.expire_time.toISOString() : null,
    })
    ElMessage.success('权限授予成功')
    permDialogVisible.value = false
    await loadPerms()
  } finally {
    saving.value = false
  }
}

async function handleRevokePerm(row) {
  await ElMessageBox.confirm(
    `确定撤销用户「${row.username}」的${permLabel(row.permission)}权限吗？撤销后按成员默认权限（只读）执行。`,
    '撤销确认',
    { type: 'warning', confirmButtonText: '撤销', cancelButtonText: '取消' },
  )
  await revokePermission(row.id)
  ElMessage.success('权限撤销成功')
  await loadPerms()
}

onMounted(async () => {
  const res = await getDepartmentTree()
  treeData.value = res.data || []
  const initial = Number(route.query.dept_id)
  if (initial && findNode(treeData.value, initial)) {
    deptId.value = initial
    await loadAll()
  }
})
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.pane-tools {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.hint {
  font-size: 12px;
  color: #94a3b8;
}
</style>
