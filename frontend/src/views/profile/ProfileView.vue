<template>
  <div class="profile">
    <el-row :gutter="20">
      <el-col :span="10">
        <el-card>
          <template #header>
            <span>账号信息</span>
          </template>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="用户名">
              {{ user.username }}
            </el-descriptions-item>
            <el-descriptions-item label="邮箱">{{ user.email }}</el-descriptions-item>
            <el-descriptions-item label="角色">
              <el-tag :type="user.role === 'admin' ? 'danger' : 'info'">
                {{ user.role === 'admin' ? '管理员' : '普通用户' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="注册时间">
              {{ formatDateTime(user.create_time) }}
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>

      <el-col :span="14">
        <el-card class="quota-card">
          <template #header>
            <span>存储空间</span>
          </template>
          <el-progress
            type="dashboard"
            :percentage="usagePercent"
            :width="160"
            :status="usagePercent >= 100 ? 'exception' : ''"
          >
            <template #default>
              <div class="quota-num">{{ usagePercent.toFixed(1) }}%</div>
            </template>
          </el-progress>
          <p class="quota-text">
            已使用 {{ formatSize(user.used_storage) }} / 共
            {{ formatSize(user.total_storage) }}
          </p>
          <p class="quota-tip">剩余可用空间：{{ formatSize(freeSpace) }}</p>
        </el-card>

        <el-card>
          <template #header>
            <span>修改密码</span>
          </template>
          <el-form
            ref="pwdFormRef"
            :model="pwdForm"
            :rules="pwdRules"
            label-width="100px"
            style="max-width: 480px"
          >
            <el-form-item label="原密码" prop="old_password">
              <el-input v-model="pwdForm.old_password" type="password" show-password />
            </el-form-item>
            <el-form-item label="新密码" prop="new_password">
              <el-input v-model="pwdForm.new_password" type="password" show-password />
            </el-form-item>
            <el-form-item label="确认新密码" prop="confirm_password">
              <el-input
                v-model="pwdForm.confirm_password"
                type="password"
                show-password
              />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="saving" @click="handleSubmit">
                保存修改
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { changePassword } from '../../api/user'
import { useUserStore } from '../../stores/user'
import { formatDateTime, formatSize } from '../../utils/format'

const userStore = useUserStore()
const user = computed(() => userStore.user || {})

const pwdFormRef = ref()
const saving = ref(false)
const pwdForm = reactive({ old_password: '', new_password: '', confirm_password: '' })

const pwdRules = {
  old_password: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, max: 64, message: '密码长度 8-64 位', trigger: 'blur' },
    {
      validator: (rule, value, cb) =>
        /[A-Za-z]/.test(value) && /\d/.test(value)
          ? cb()
          : cb(new Error('密码须同时包含字母和数字')),
      trigger: 'blur',
    },
  ],
  confirm_password: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (rule, value, cb) =>
        value === pwdForm.new_password ? cb() : cb(new Error('两次输入不一致')),
      trigger: 'blur',
    },
  ],
}

const usagePercent = computed(() => {
  if (!user.value.total_storage) return 0
  return Math.min((user.value.used_storage / user.value.total_storage) * 100, 100)
})

const freeSpace = computed(() =>
  Math.max((user.value.total_storage || 0) - (user.value.used_storage || 0), 0),
)

async function handleSubmit() {
  await pwdFormRef.value.validate(async (valid) => {
    if (!valid) return
    saving.value = true
    try {
      await changePassword(pwdForm.old_password, pwdForm.new_password)
      ElMessage.success('密码修改成功')
      pwdFormRef.value.resetFields()
    } finally {
      saving.value = false
    }
  })
}

onMounted(() => {
  if (!userStore.user) userStore.fetchInfo()
})
</script>

<style scoped>
.quota-card {
  margin-bottom: 20px;
  text-align: center;
}

.quota-num {
  font-size: 22px;
  font-weight: 600;
  color: #2563eb;
}

.quota-text {
  margin: 12px 0 4px;
  color: #475569;
}

.quota-tip {
  margin: 0;
  color: #94a3b8;
  font-size: 13px;
}
</style>
