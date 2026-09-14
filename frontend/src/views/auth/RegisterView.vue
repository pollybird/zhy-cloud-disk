<template>
  <div class="auth-wrapper">
    <el-card class="auth-card" shadow="always">
      <div class="brand">
        <el-icon :size="28" color="#2563eb"><Cloudy /></el-icon>
        <h2>注册新账号</h2>
      </div>

      <el-skeleton v-if="statusLoading" :rows="4" animated />

      <template v-else>
        <el-alert
          v-if="!registerOpen"
          title="系统当前未开放公开注册"
          description="如需账号，请联系管理员在后台为你创建。"
          type="warning"
          show-icon
          :closable="false"
          class="closed-tip"
        />

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-position="top"
          :disabled="!registerOpen"
        >
          <el-form-item label="用户名" prop="username">
            <el-input v-model="form.username" placeholder="3-32 位中英文、数字" size="large" />
          </el-form-item>
          <el-form-item label="邮箱" prop="email">
            <el-input v-model="form.email" placeholder="请输入邮箱" size="large" />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              type="password"
              show-password
              placeholder="8-64 位，须包含字母和数字"
              size="large"
            />
          </el-form-item>
          <el-form-item label="确认密码" prop="confirm">
            <el-input
              v-model="form.confirm"
              type="password"
              show-password
              placeholder="再次输入密码"
              size="large"
            />
          </el-form-item>
          <el-button
            type="primary"
            size="large"
            class="submit"
            :loading="loading"
            :disabled="!registerOpen"
            @click="handleRegister"
          >
            注 册
          </el-button>
        </el-form>
      </template>

      <div class="footer">
        <span>已有账号？</span>
        <router-link to="/login">返回登录</router-link>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '../../stores/user'

const router = useRouter()
const userStore = useUserStore()
const formRef = ref()
const loading = ref(false)

const form = reactive({ username: '', email: '', password: '', confirm: '' })

const rules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    {
      pattern: /^[A-Za-z0-9_\-一-龥]{3,32}$/,
      message: '3-32 位中英文、数字、下划线或连字符',
      trigger: 'blur',
    },
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 8, max: 64, message: '密码长度 8-64 位', trigger: 'blur' },
    {
      validator: (rule, value, cb) =>
        /[A-Za-z]/.test(value) && /\d/.test(value)
          ? cb()
          : cb(new Error('密码须同时包含字母和数字')),
      trigger: 'blur',
    },
  ],
  confirm: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    {
      validator: (rule, value, cb) =>
        value === form.password ? cb() : cb(new Error('两次输入不一致')),
      trigger: 'blur',
    },
  ],
}

async function handleRegister() {
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      await userStore.register(form.username, form.email, form.password)
      ElMessage.success('注册成功，请登录')
      router.replace('/login')
    } finally {
      loading.value = false
    }
  })
}
</script>

<style scoped>
.auth-wrapper {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%);
}

.auth-card {
  width: 420px;
  max-width: 92vw;
  border-radius: 12px;
}

.brand {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin-bottom: 20px;
}

.brand h2 {
  margin: 0;
  color: #1e293b;
}

.submit {
  width: 100%;
}

.closed-tip {
  margin-bottom: 18px;
}

.footer {
  margin-top: 16px;
  text-align: center;
  font-size: 13px;
  color: #64748b;
}

.footer a {
  color: #2563eb;
  text-decoration: none;
  margin-left: 4px;
}
</style>
