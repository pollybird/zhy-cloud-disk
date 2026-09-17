<template>
  <el-card class="dept-card">
    <template #header>
      <div class="card-header">
        <span>部门管理</span>
        <div class="tools">
          <el-button v-if="userStore.isAdmin" type="primary" @click="openCreate(null)">
            <el-icon><Plus /></el-icon>&nbsp;新增根部门
          </el-button>
          <el-button @click="reload">
            <el-icon><Refresh /></el-icon>&nbsp;刷新
          </el-button>
        </div>
      </div>
    </template>

    <div class="dept-layout">
      <!-- 左侧：部门树 -->
      <div class="tree-pane">
        <el-tree
          ref="treeRef"
          v-loading="loading"
          :data="treeData"
          :props="{ label: 'name', children: 'children' }"
          node-key="id"
          default-expand-all
          highlight-current
          :expand-on-click-node="false"
          @node-click="onSelect"
        >
          <template #default="{ data }">
            <span class="tree-node">
              <el-icon><OfficeBuilding /></el-icon>
              <span>{{ data.name }}</span>
              <el-tag v-if="isDeptAdmin(data.id)" size="small" type="warning" effect="plain">
                我管理
              </el-tag>
            </span>
          </template>
        </el-tree>
        <el-empty v-if="!loading && treeData.length === 0" description="暂无部门" />
      </div>

      <!-- 右侧：详情与操作 -->
      <div class="detail-pane">
        <template v-if="selected">
          <el-descriptions :column="2" border title="部门详情">
            <el-descriptions-item label="ID">{{ selected.id }}</el-descriptions-item>
            <el-descriptions-item label="名称">{{ selected.name }}</el-descriptions-item>
            <el-descriptions-item label="排序">{{ selected.sort_order }}</el-descriptions-item>
            <el-descriptions-item label="状态">
              <el-tag :type="selected.status === 'active' ? 'success' : 'info'" size="small">
                {{ selected.status === 'active' ? '启用' : '停用' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="空间使用" :span="2">
              {{ formatSize(selected.used_storage) }} /
              {{ selected.storage_quota ? formatSize(selected.storage_quota) : '不限' }}
            </el-descriptions-item>
          </el-descriptions>

          <div class="action-bar">
            <el-button v-if="canManage(selected.id)" type="primary" @click="openCreate(selected.id)">
              新增子部门
            </el-button>
            <el-button v-if="canManage(selected.id)" @click="openEdit">编辑</el-button>
            <el-button v-if="canManage(selected.id)" type="danger" plain @click="handleDelete">
              删除
            </el-button>
            <el-button v-if="userStore.isAdmin" @click="openMove">迁移</el-button>
          </div>
          <div class="action-bar">
            <el-button v-if="canManage(selected.id)" @click="goMembers">
              成员管理
            </el-button>
            <el-button v-if="canManage(selected.id)" @click="goPermissions">
              权限配置
            </el-button>
          </div>
        </template>
        <el-empty v-else description="请在左侧选择部门" />
      </div>
    </div>

    <!-- 新增 / 编辑部门 -->
    <el-dialog
      v-model="formVisible"
      :title="formMode === 'create' ? '新增部门' : `编辑部门：${form.name}`"
      width="440px"
      :close-on-click-modal="false"
    >
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="90px">
        <el-form-item label="部门名称" prop="name">
          <el-input v-model="form.name" maxlength="128" placeholder="部门名称" />
        </el-form-item>
        <el-form-item v-if="formMode === 'create'" label="上级部门">
          <el-input :model-value="parentName" disabled />
        </el-form-item>
        <el-form-item v-else label="同级排序" prop="sort_order">
          <el-input-number v-model="form.sort_order" :min="0" :max="9999" />
        </el-form-item>
        <el-form-item
          v-if="formMode === 'edit' && userStore.isAdmin"
          label="空间配额(GB)"
        >
          <el-input-number
            v-model="form.storage_quota_gb"
            :min="0"
            :precision="2"
            :step="1"
          />
          <span class="quota-hint">0 表示不限；不能低于当前已用空间</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>

    <!-- 迁移部门 -->
    <el-dialog v-model="moveVisible" title="迁移部门" width="440px" :close-on-click-modal="false">
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="迁移后该部门及其全部子部门将挂到新的上级部门下"
        class="move-tip"
      />
      <el-form label-width="90px">
        <el-form-item label="新上级部门">
          <el-tree-select
            v-model="moveTarget"
            :data="moveOptions"
            check-strictly
            :render-after-expand="false"
            default-expand-all
            placeholder="选择新上级部门（不选则设为根部门）"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="moveVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleMove">确定迁移</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import {
  createDepartment,
  deleteDepartment,
  getDepartmentTree,
  moveDepartment,
  updateDepartment,
} from '../../api/department'
import { useUserStore } from '../../stores/user'
import { formatSize } from '../../utils/format'

const router = useRouter()
const userStore = useUserStore()

const loading = ref(false)
const saving = ref(false)
const treeData = ref([])
const selected = ref(null)
const treeRef = ref()

// id -> 节点映射（权限判断用）
const nodeMap = computed(() => {
  const map = {}
  const walk = (nodes, parent) => {
    for (const n of nodes) {
      map[n.id] = { ...n, _parent: parent }
      if (n.children?.length) walk(n.children, n.id)
    }
  }
  walk(treeData.value, null)
  return map
})

function isDeptAdmin(deptId) {
  return userStore.adminDepts.some((a) => a.department_id === deptId)
}

/** 是否有权管理该部门：超管，或本部门/祖先部门管理员（self_and_sub） */
function canManage(deptId) {
  if (userStore.isAdmin) return true
  let node = nodeMap.value[deptId]
  while (node) {
    const ad = userStore.adminDepts.find((a) => a.department_id === node.id)
    if (ad) return ad.scope === 'self_and_sub' || node.id === deptId
    node = node._parent != null ? nodeMap.value[node._parent] : null
  }
  return false
}

async function reload() {
  loading.value = true
  try {
    const res = await getDepartmentTree()
    treeData.value = res.data || []
    if (selected.value) {
      const fresh = nodeMap.value[selected.value.id]
      selected.value = fresh || null
      await nextTick()
      if (fresh) treeRef.value?.setCurrentKey(fresh.id)
    }
  } finally {
    loading.value = false
  }
}

function onSelect(data) {
  selected.value = data
}

// ---------------------------------------------------------------------------
// 新增 / 编辑
// ---------------------------------------------------------------------------

const formVisible = ref(false)
const formMode = ref('create')
const formRef = ref()
const form = reactive({ id: null, name: '', sort_order: 0, parent_id: null })

const formRules = {
  name: [
    { required: true, message: '请输入部门名称', trigger: 'blur' },
    { max: 128, message: '名称最长 128 字', trigger: 'blur' },
  ],
}

const parentName = computed(() => {
  if (formMode.value !== 'create' || !form.parent_id) return '（根部门）'
  return nodeMap.value[form.parent_id]?.name || '-'
})

function openCreate(parentId) {
  formMode.value = 'create'
  form.id = null
  form.name = ''
  form.parent_id = parentId
  formVisible.value = true
}

function openEdit() {
  if (!selected.value) return
  formMode.value = 'edit'
  form.id = selected.value.id
  form.name = selected.value.name
  form.sort_order = selected.value.sort_order
  formVisible.value = true
}

async function handleSave() {
  await formRef.value.validate()
  saving.value = true
  try {
    if (formMode.value === 'create') {
      await createDepartment({ name: form.name.trim(), parent_id: form.parent_id })
      ElMessage.success('部门创建成功')
    } else {
      await updateDepartment(form.id, {
        name: form.name.trim(),
        sort_order: form.sort_order,
      })
      ElMessage.success('部门更新成功')
    }
    formVisible.value = false
    await reload()
  } finally {
    saving.value = false
  }
}

async function handleDelete() {
  if (!selected.value) return
  const dept = selected.value
  await ElMessageBox.confirm(
    `确定删除部门「${dept.name}」吗？其全部空子部门、成员与管理员关联将一并删除；若部门下仍有文件或文件夹，需先迁移或清空后才能删除。`,
    '删除确认',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
  )
  await deleteDepartment(dept.id)
  ElMessage.success('部门删除成功')
  selected.value = null
  await reload()
}

// ---------------------------------------------------------------------------
// 迁移
// ---------------------------------------------------------------------------

const moveVisible = ref(false)
const moveTarget = ref(null)

const moveOptions = computed(() => {
  // 排除自身及子树，防止移到自己下面（后端也会校验）
  const currentId = selected.value?.id
  const filterTree = (nodes) =>
    nodes
      .filter((n) => n.id !== currentId)
      .map((n) => ({ ...n, children: n.children?.length ? filterTree(n.children) : [] }))
  return filterTree(treeData.value)
})

function openMove() {
  moveTarget.value = selected.value?.parent_id ?? null
  moveVisible.value = true
}

async function handleMove() {
  saving.value = true
  try {
    await moveDepartment(selected.value.id, moveTarget.value)
    ElMessage.success('部门迁移成功')
    moveVisible.value = false
    await reload()
  } finally {
    saving.value = false
  }
}

// ---------------------------------------------------------------------------
// 跳转
// ---------------------------------------------------------------------------

function goMembers() {
  router.push({ path: '/department-members', query: { dept_id: selected.value.id } })
}

function goPermissions() {
  router.push({ path: '/admin/permissions', query: { dept_id: selected.value.id } })
}

onMounted(async () => {
  if (!userStore.adminDeptsLoaded) await userStore.fetchAdminDepts()
  await reload()
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

.dept-layout {
  display: flex;
  gap: 24px;
  min-height: 420px;
}

.tree-pane {
  width: 320px;
  flex-shrink: 0;
  border-right: 1px solid #e5e7eb;
  padding-right: 16px;
}

.tree-node {
  display: flex;
  align-items: center;
  gap: 6px;
}

.detail-pane {
  flex: 1;
}

.action-bar {
  display: flex;
  gap: 8px;
  margin-top: 16px;
}

.move-tip {
  margin-bottom: 16px;
}
</style>
