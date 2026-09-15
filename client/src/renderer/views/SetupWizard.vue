<template>
  <div class="wizard-container">
    <el-card class="wizard-card" shadow="always">
      <template #header>
        <div class="wizard-header">
          <h2>钟毓云盘 - 初始设置</h2>
        </div>
      </template>

      <el-steps :active="step" finish-status="success" align-center>
        <el-step title="服务器" />
        <el-step title="账号" />
        <el-step title="同步路径" />
        <el-step title="完成" />
      </el-steps>

      <!-- 步骤 1：服务器地址 -->
      <div v-if="step === 0" class="step-content">
        <el-form label-position="top">
          <el-form-item label="服务器地址">
            <el-input
              v-model="serverUrl"
              placeholder="http://192.168.1.10:8080"
              clearable
            >
              <template #prepend>
                <el-icon><Link /></el-icon>
              </template>
            </el-input>
          </el-form-item>
          <el-button type="primary" :loading="testing" @click="testConnection">
            测试连接
          </el-button>
        </el-form>
      </div>

      <!-- 步骤 2：账号密码 -->
      <div v-if="step === 1" class="step-content">
        <el-form label-position="top">
          <el-form-item label="用户名">
            <el-input v-model="username" placeholder="admin" clearable />
          </el-form-item>
          <el-form-item label="密码">
            <el-input
              v-model="password"
              type="password"
              show-password
              placeholder="请输入密码"
              @keyup.enter="doLogin"
            />
          </el-form-item>
          <el-button type="primary" :loading="logging" @click="doLogin">
            登录
          </el-button>
        </el-form>
      </div>

      <!-- 步骤 3：同步路径 -->
      <div v-if="step === 2" class="step-content">
        <el-form label-position="top">
          <el-form-item label="本地同步文件夹">
            <el-input v-model="syncPath" readonly placeholder="请选择同步目录">
              <template #append>
                <el-button @click="chooseFolder">
                  <el-icon><FolderOpened /></el-icon>&nbsp;选择
                </el-button>
              </template>
            </el-input>
          </el-form-item>
          <el-alert
            title="首次同步将下载云端所有文件到此目录"
            type="info"
            :closable="false"
            show-icon
          />
        </el-form>
      </div>

      <!-- 步骤 4：确认 -->
      <div v-if="step === 3" class="step-content">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="服务器">{{ serverUrl }}</el-descriptions-item>
          <el-descriptions-item label="账号">{{ username }}</el-descriptions-item>
          <el-descriptions-item label="同步路径">{{ syncPath }}</el-descriptions-item>
        </el-descriptions>
        <el-checkbox v-model="autoStart" style="margin-top: 16px">
          开机自动启动
        </el-checkbox>
        <el-button
          type="success"
          style="margin-top: 16px"
          :loading="finishing"
          @click="finish"
        >
          开始同步
        </el-button>
      </div>

      <!-- 导航按钮 -->
      <div class="step-nav">
        <el-button v-if="step > 0" @click="step--">上一步</el-button>
        <el-button v-if="step < 3 && step !== 1" type="primary" @click="step++">
          下一步
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Link, FolderOpened } from '@element-plus/icons-vue'
import { useSettingsStore } from '../stores/settings.js'

const router = useRouter()
const store = useSettingsStore()

const step = ref(0)
const serverUrl = ref('http://127.0.0.1:5000')
const username = ref('')
const password = ref('')
const syncPath = ref('')
const autoStart = ref(true)

const testing = ref(false)
const logging = ref(false)
const finishing = ref(false)

async function testConnection() {
  if (!serverUrl.value) {
    ElMessage.warning('请输入服务器地址')
    return
  }
  testing.value = true
  try {
    const res = await window.zhy.testConnection(serverUrl.value)
    if (res.success) {
      ElMessage.success(`连接成功，版本 ${res.data.version}`)
      step.value = 1
    } else {
      ElMessage.error(`连接失败：${res.error}`)
    }
  } catch (e) {
    ElMessage.error(`连接失败：${e.message}`)
  } finally {
    testing.value = false
  }
}

async function doLogin() {
  if (!username.value || !password.value) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  logging.value = true
  try {
    const res = await window.zhy.login(serverUrl.value, username.value, password.value)
    if (res.success) {
      ElMessage.success(`登录成功：${res.user.username}`)
      step.value = 2
    } else {
      ElMessage.error(`登录失败：${res.error}`)
    }
  } catch (e) {
    ElMessage.error(`登录失败：${e.message}`)
  } finally {
    logging.value = false
  }
}

async function chooseFolder() {
  const dir = await window.zhy.chooseFolder()
  if (dir) {
    syncPath.value = dir
  }
}

async function finish() {
  if (!syncPath.value) {
    ElMessage.warning('请选择同步目录')
    return
  }
  finishing.value = true
  try {
    await store.saveSettings({
      serverUrl: serverUrl.value,
      username: username.value,
      syncPath: syncPath.value,
      autoStart: autoStart.value,
      configured: true,
    })
    await window.zhy.setAutoStart(autoStart.value)
    const res = await window.zhy.startSync()
    if (res && res.success === false) {
      ElMessage.error(`同步启动失败：${res.error || '未知错误'}`)
      return
    }
    ElMessage.success('同步已启动')
    router.push('/sync')
  } catch (e) {
    ElMessage.error(`启动失败：${e.message}`)
  } finally {
    finishing.value = false
  }
}
</script>

<style scoped>
.wizard-header h2 {
  text-align: center;
  margin: 0;
}
.step-content {
  min-height: 200px;
  padding: 20px 10px;
}
.step-nav {
  text-align: center;
  margin-top: 16px;
}
</style>
