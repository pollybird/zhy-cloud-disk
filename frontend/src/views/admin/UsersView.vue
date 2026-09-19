<template>
  <el-card>
    <template #header>
      <div class="card-header">
        <span>用户管理</span>
        <div class="tools">
          <el-button type="primary" @click="openCreate">
            <el-icon><Plus /></el-icon>&nbsp;添加用户
          </el-button>
          <el-input
            v-model="keyword"
            placeholder="搜索用户名 / 邮箱"
            clearable
            style="width: 220px"
            @keyup.enter="reloadFirst"
            @clear="reloadFirst"
          />
          <el-button @click="reloadFirst">查询</el-button>
        </div>
      </div>
    </template>

    <el-table :data="rows" v-loading="loading" border stripe style="margin-top: 12px">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="username" label="用户名" min-width="120" />
      <el-table-column prop="email" label="邮箱" min-width="180" />
      <el-table-column label="角色" width="90">
        <template #default="{ row }">
          <el-tag :type="row.role === 'admin' ? 'danger' : 'info'" size="small">
            {{ row.role === 'admin' ? '管理员' : '用户' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'warning'" size="small">
            {{ row.status === 'active' ? '正常' : '禁用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="空间使用" min-width="170">
        <template #default="{ row }">
          {{ formatSize(row.used_storage) }} / {{ formatSize(row.total_storage) }}
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="165">
        <template #default="{ row }">{{ formatDateTime(row.create_time) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button
            v-if="row.status === 'active'"
            link
            type="warning"
            :disabled="row.id === currentUserId"
            @click="toggleStatus(row, 'disabled')"
          >
            禁用
          </el-button>
          <el-button v-else link type="success" @click="toggleStatus(row, 'active')">
            启用
          </el-button>
        </template>
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

    <!-- 添加 / 编辑用户对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="dialogMode === 'create' ? '添加用户' : `编辑用户：${form.username}`"
      width="500px"
      :close-on-click-modal="false"
      @closed="resetForm"
    >
      <el-form
        ref="formRef"
        :model="form"
        :rules="formRules"
        label-width="100px"
      >
        <el-form-item v-if="dialogMode === 'create'" label="用户名" prop="username">
          <el-input v-model="form.username" placeholder="3-32 位中英文、数字、下划线或连字符" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="form.email" placeholder="请输入邮箱" />
        </el-form-item>
        <el-form-item label="角色" prop="role">
          <el-radio-group v-model="form.role" :disabled="dialogMode === 'edit' && form.id === currentUserId">
            <el-radio value="user">普通用户</el-radio>
            <el-radio value="admin">管理员</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="账号状态">
          <el-switch
            v-model="form.statusActive"
            active-text="正常"
            inactive-text="禁用"
            :disabled="dialogMode === 'edit' && form.id === currentUserId"
          />
          <span v-if="dialogMode === 'edit' && form.id === currentUserId" class="hint">
            不能修改自己的状态
          </span>
        </el-form-item>
        <el-form-item label="空间配额">
          <el-input-number
            v-model="form.quotaGb"
            :min="minQuotaGb"
            :precision="2"
            :step="1"
            style="width: 200px"
          />
          <span class="unit">GB</span>
          <div v-if="dialogMode === 'edit'" class="hint">
            已使用 {{ formatSize(editingUsed) }}，配额不可低于该值
          </div>
        </el-form-item>
        <el-form-item
          :label="dialogMode === 'create' ? '初始密码' : '重置密码'"
          prop="password"
        >
          <el-input
            v-model="form.password"
            type="password"
            show-password
            :placeholder="dialogMode === 'create'
              ? '8-64 位，须包含字母和数字'
              : '留空表示不修改密码'"
          />
          <div
            v-if="dialogMode === 'edit' && form.id === currentUserId"
            class="hint"
          >
            不能在此重置自己的密码，请到「个人中心」修改
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createUser,
  listUsers,
  setUserStatus,
  updateUser,
} from '../../api/user'
import { useUserStore } from '../../stores/user'
import { formatDateTime, formatSize } from '../../utils/format'

const GB = 1024 ** 3

const userStore = useUserStore()
const currentUserId = computed(() => userStore.user?.id)

const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const keyword = ref('')
const loading = ref(false)

const dialogVisible = ref(false)
const dialogMode = ref('create') // create | edit
const saving = ref(false)
const formRef = ref()
const editingUsed = ref(0)

const defaultForm = () => ({
  id: null,
  username: '',
  email: '',
  role: 'user',
  statusActive: true,
  quotaGb: 5,
  password: '',
})
const form = reactive(defaultForm())

const minQuotaGb = computed(() => Math.max(editingUsed.value / GB, 0.01))

const formRules = computed(() => ({
  username:
    dialogMode.value === 'create'
      ? [
          { required: true, message: '请输入用户名', trigger: 'blur' },
          {
            pattern: /^[A-Za-z0-9_\-一-龥]{3,32}$/,
            message: '3-32 位中英文、数字、下划线或连字符',
            trigger: 'blur',
          },
        ]
      : [],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' },
  ],
  password:
    dialogMode.value === 'create'
      ? [
          { required: true, message: '请输入初始密码', trigger: 'blur' },
          { min: 8, max: 64, message: '密码长度 8-64 位', trigger: 'blur' },
          {
            validator: (rule, value, cb) =>
              /[A-Za-z]/.test(value) && /\d/.test(value)
                ? cb()
                : cb(new Error('密码须同时包含字母和数字')),
            trigger: 'blur',
          },
        ]
      : [
          {
            validator: (rule, value, cb) => {
              if (!value) return cb()
              if (value.length < 8 || value.length > 64) return cb(new Error('密码长度 8-64 位'))
              if (!/[A-Za-z]/.test(value) || !/\d/.test(value)) {
                return cb(new Error('密码须同时包含字母和数字'))
              }
              cb()
            },
            trigger: 'blur',
          },
        ],
}))

async function loadData() {
  loading.value = true
  try {
    const res = await listUsers({
      q: keyword.value,
      page: page.value,
      size: size.value,
    })
    rows.value = res.data.items
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}

function reloadFirst() {
  page.value = 1
  loadData()
}

function onPageChange(p) {
  page.value = p
  loadData()
}

function openCreate() {
  dialogMode.value = 'create'
  Object.assign(form, defaultForm())
  dialogVisible.value = true
}

function openEdit(row) {
  dialogMode.value = 'edit'
  editingUsed.value = row.used_storage || 0
  Object.assign(form, {
    id: row.id,
    username: row.username,
    email: row.email,
    role: row.role,
    statusActive: row.status === 'active',
    quotaGb: Math.max(row.total_storage / GB, minQuotaGb.value),
    password: '',
  })
  dialogVisible.value = true
}

function resetForm() {
  Object.assign(form, defaultForm())
  formRef.value?.clearValidate?.()
}

async function handleSave() {
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    saving.value = true
    try {
      const isSelf = dialogMode.value === 'edit' && form.id === currentUserId.value
      if (dialogMode.value === 'create') {
        await createUser({
          username: form.username.trim(),
          email: form.email.trim(),
          password: form.password,
          role: form.role,
          status: form.statusActive ? 'active' : 'disabled',
          total_storage: Math.round(form.quotaGb * GB),
        })
        ElMessage.success('用户创建成功')
      } else {
        const payload = {
          email: form.email.trim(),
          total_storage: Math.round(form.quotaGb * GB),
        }
        // 自己的角色/状态/密码服务端禁止修改，前端直接不下发
        if (!isSelf) {
          payload.role = form.role
          payload.status = form.statusActive ? 'active' : 'disabled'
          if (form.password) payload.new_password = form.password
        }
        await updateUser(form.id, payload)
        ElMessage.success('用户信息已更新')
      }
      dialogVisible.value = false
      loadData()
    } finally {
      saving.value = false
    }
  })
}

async function toggleStatus(row, status) {
  const action = status === 'disabled' ? '禁用' : '启用'
  await ElMessageBox.confirm(`确定${action}用户「${row.username}」吗？`, '提示', {
    type: 'warning',
  })
  await setUserStatus(row.id, status)
  ElMessage.success(`已${action}`)
  loadData()
}

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.tools {
  display: flex;
  align-items: center;
  gap: 10px;
}

.pager {
  margin-top: 16px;
  justify-content: flex-end;
}

.unit {
  margin-left: 8px;
  color: #64748b;
}

.hint {
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.6;
  margin-left: 12px;
}
</style>
