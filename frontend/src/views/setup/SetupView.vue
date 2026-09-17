<template>
  <div class="setup-wrapper">
    <el-card class="setup-card" shadow="always">
      <template #header>
        <div class="setup-header">
          <h2>钟毓私有云盘 · 安装向导</h2>
          <p class="sub">首次运行，请完成环境检测、数据库配置与超级管理员初始化</p>
        </div>
      </template>

      <el-steps :active="active" align-center finish-status="success" class="steps">
        <el-step title="欢迎" />
        <el-step title="环境检测" />
        <el-step title="数据库" />
        <el-step title="功能选项" />
        <el-step title="管理员" />
        <el-step title="完成" />
      </el-steps>

      <!-- 步骤零：欢迎 / 版权信息 -->
      <div v-show="active === 0" class="step-pane welcome-pane">
        <div class="welcome-content">
          <el-icon class="welcome-logo"><Cloudy /></el-icon>
          <h1 class="welcome-title">钟毓私有云盘</h1>
          <p class="welcome-version">版本 {{ ZHY_VERSION }}</p>
          <el-divider class="welcome-divider" />
          <p class="welcome-copyright">
            Copyright &copy; 2026 泰州姜堰钟毓信息技术有限公司
          </p>
          <p class="welcome-license">
            本软件基于 Apache License 2.0 开源，详见 LICENSE 文件。
          </p>
        </div>
        <div class="step-actions">
          <el-button type="primary" size="large" @click="enterSetup">
            确定 &nbsp;
            <el-icon><Right /></el-icon>
          </el-button>
        </div>
      </div>

      <!-- 步骤一：环境检测 -->
      <div v-show="active === 1" class="step-pane">
        <el-skeleton v-if="envLoading" :rows="5" animated />
        <el-descriptions v-else :column="1" border>
          <el-descriptions-item label="系统版本">
            {{ env.platform }}
          </el-descriptions-item>
          <el-descriptions-item label="Python 版本">
            {{ env.python_version }}
          </el-descriptions-item>
          <el-descriptions-item label="安装目录可写">
            <el-tag :type="env.instance_writable ? 'success' : 'danger'">
              {{ env.instance_writable ? '可写' : '不可写' }}
            </el-tag>
            <span class="path-hint">{{ env.instance_dir }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="默认存储目录可写">
            <el-tag :type="env.storage_writable ? 'success' : 'danger'">
              {{ env.storage_writable ? '可写' : '不可写' }}
            </el-tag>
            <span class="path-hint">{{ env.storage_dir }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="磁盘剩余空间">
            {{ formatSize(env.disk_free) }}
          </el-descriptions-item>
        </el-descriptions>

        <el-alert
          v-if="!envLoading && (!env.instance_writable || !env.storage_writable)"
          title="存在不可写目录，请先修复目录权限后刷新重试"
          type="error"
          :closable="false"
          show-icon
          class="step-alert"
        />

        <div class="step-actions">
          <el-button @click="loadEnvironment" :loading="envLoading">
            <el-icon><Refresh /></el-icon>&nbsp;重新检测
          </el-button>
          <el-button
            type="primary"
            :disabled="envLoading || !env.instance_writable || !env.storage_writable"
            @click="active = 2"
          >
            下一步
          </el-button>
        </div>
      </div>

      <!-- 步骤二：数据库配置 -->
      <div v-show="active === 2" class="step-pane">
        <el-form :model="dbForm" label-width="110px">
          <el-form-item label="数据库类型">
            <el-radio-group v-model="dbForm.db_type" @change="onDbTypeChange">
              <el-radio-button value="sqlite">SQLite（零配置）</el-radio-button>
              <el-radio-button value="mysql">MySQL</el-radio-button>
              <el-radio-button value="postgresql">PostgreSQL</el-radio-button>
            </el-radio-group>
          </el-form-item>

          <template v-if="dbForm.db_type === 'sqlite'">
            <el-form-item label="数据库文件名">
              <el-input v-model="dbForm.database" placeholder="zhycloud.db" />
            </el-form-item>
          </template>

          <template v-else>
            <el-form-item label="填写方式">
              <el-radio-group v-model="dbInputMode" @change="resetDbTested">
                <el-radio-button value="form">连接参数</el-radio-button>
                <el-radio-button value="dsn">连接字符串</el-radio-button>
              </el-radio-group>
            </el-form-item>

            <template v-if="dbInputMode === 'form'">
              <el-form-item label="主机地址">
                <el-input v-model="dbForm.host" placeholder="127.0.0.1" />
              </el-form-item>
              <el-form-item label="端口">
                <el-input
                  v-model="dbForm.port"
                  :placeholder="dbForm.db_type === 'mysql' ? '3306' : '5432'"
                />
              </el-form-item>
              <el-form-item label="数据库名">
                <el-input v-model="dbForm.database" placeholder="zhycloud" />
              </el-form-item>
              <el-form-item label="用户名">
                <el-input v-model="dbForm.username" />
              </el-form-item>
              <el-form-item label="密码">
                <el-input v-model="dbForm.password" type="password" show-password />
              </el-form-item>
            </template>

            <el-form-item v-else label="连接字符串">
              <el-input
                v-model="dsnUri"
                type="textarea"
                :rows="3"
                :placeholder="dbForm.db_type === 'mysql'
                  ? 'mysql+pymysql://用户:密码@127.0.0.1:3306/zhycloud?charset=utf8mb4'
                  : 'postgresql+psycopg2://用户:密码@127.0.0.1:5432/zhycloud'"
                @input="resetDbTested"
              />
              <div class="form-tip">直接粘贴完整 SQLAlchemy 连接串，密码将仅用于本次连接、不会写入日志</div>
            </el-form-item>
          </template>

          <el-form-item>
            <el-button @click="handleTestDb" :loading="dbTesting">
              <el-icon><Connection /></el-icon>&nbsp;测试连接
            </el-button>
            <el-tag v-if="dbTested" type="success" class="tested-tag">
              连接与写权限校验通过
            </el-tag>
          </el-form-item>

          <el-divider content-position="left">Redis 缓存（可选）</el-divider>
          <el-form-item label="Redis 连接地址">
            <el-input
              v-model="dbForm.redis_url"
              placeholder="redis://127.0.0.1:6379/0（留空则使用内存缓存）"
            />
            <div class="form-tip">
              配置 Redis 后可用于：系统设置缓存、分享密码限频、JWT 吊销列表、插件状态同步。
              留空或不配置 Redis 时系统正常运行（降级为进程内内存缓存，多 worker 下限频可能不完全一致）。
            </div>
          </el-form-item>
        </el-form>

        <div class="step-actions">
          <el-button @click="active = 1">上一步</el-button>
          <el-button type="primary" :disabled="!dbTested" @click="active = 3">
            下一步
          </el-button>
        </div>
      </div>

      <!-- 步骤三：功能选项 -->
      <div v-show="active === 3" class="step-pane">
        <el-form label-width="110px">
          <el-form-item label="功能模块">
            <el-checkbox v-model="enableDepartment" class="feature-checkbox">
              开启部门共享网盘
            </el-checkbox>
            <div class="form-tip feature-tip">
              启用多级部门组织架构、分级管理员委派与成员权限管控（只读 / 读写 / 禁止访问）。
              <br />
              不勾选则仅保留个人独立网盘功能；安装后可在系统设置中更改。
            </div>
          </el-form-item>
        </el-form>

        <div class="step-actions">
          <el-button @click="active = 2">上一步</el-button>
          <el-button type="primary" @click="active = 4">下一步</el-button>
        </div>
      </div>

      <!-- 步骤四：超级管理员 -->
      <div v-show="active === 4" class="step-pane">
        <el-form
          ref="adminFormRef"
          :model="adminForm"
          :rules="adminRules"
          label-width="130px"
        >
          <el-form-item label="存储目录" prop="storage_dir">
            <el-input
              v-model="adminForm.storage_dir"
              placeholder="留空使用默认 storage/ 目录"
            />
          </el-form-item>
          <el-form-item label="管理员用户名" prop="admin_username">
            <el-input v-model="adminForm.admin_username" placeholder="3-32 位中英文、数字" />
          </el-form-item>
          <el-form-item label="管理员邮箱" prop="admin_email">
            <el-input v-model="adminForm.admin_email" placeholder="admin@example.com" />
          </el-form-item>
          <el-form-item label="登录密码" prop="admin_password">
            <el-input
              v-model="adminForm.admin_password"
              type="password"
              show-password
              placeholder="8-64 位，须包含字母和数字"
            />
          </el-form-item>
          <el-form-item label="确认密码" prop="confirm_password">
            <el-input
              v-model="adminForm.confirm_password"
              type="password"
              show-password
              placeholder="再次输入密码"
            />
          </el-form-item>
        </el-form>

        <div class="step-actions">
          <el-button @click="active = 3">上一步</el-button>
          <el-button type="primary" @click="handleSubmit">
            <el-icon><Check /></el-icon>&nbsp;开始安装
          </el-button>
        </div>
      </div>

      <!-- 步骤五：执行结果 -->
      <div v-show="active === 5" class="step-pane result-pane">
        <el-result
          :icon="installing ? 'info' : 'success'"
          :title="installing ? '正在安装…' : '安装完成'"
          :sub-title="installing ? '正在创建数据表与超级管理员，请勿关闭页面' : resultText"
        >
          <template v-if="installing" #extra>
            <el-progress :percentage="installProgress" striped striped-flow />
          </template>
          <template v-else #extra>
            <el-button type="primary" @click="goLogin">前往登录</el-button>
          </template>
        </el-result>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getEnvironment, install, testDatabase } from '../../api/setup'
import { ZHY_VERSION } from '../../constants'

const active = ref(0)
const envLoading = ref(false)
const env = reactive({
  python_version: '',
  platform: '',
  instance_dir: '',
  instance_writable: false,
  storage_dir: '',
  storage_writable: false,
  disk_free: 0,
})

const dbTesting = ref(false)
const dbTested = ref(false)
const dbInputMode = ref('form')
const dsnUri = ref('')
const dbForm = reactive({
  db_type: 'sqlite',
  database: 'zhycloud',
  host: '127.0.0.1',
  port: '',
  username: '',
  password: '',
  redis_url: '',
})

const adminFormRef = ref()
const enableDepartment = ref(false)
const adminForm = reactive({
  storage_dir: '',
  admin_username: '',
  admin_email: '',
  admin_password: '',
  confirm_password: '',
})

const validatePass2 = (rule, value, callback) => {
  if (value !== adminForm.admin_password) {
    callback(new Error('两次输入的密码不一致'))
  } else {
    callback()
  }
}

const adminRules = {
  admin_username: [
    { required: true, message: '请输入管理员用户名', trigger: 'blur' },
    {
      pattern: /^[A-Za-z0-9_\-一-龥]{3,32}$/,
      message: '3-32 位中英文、数字、下划线或连字符',
      trigger: 'blur',
    },
  ],
  admin_email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' },
  ],
  admin_password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 8, max: 64, message: '密码长度 8-64 位', trigger: 'blur' },
    {
      validator: (rule, value, callback) => {
        if (/[A-Za-z]/.test(value) && /\d/.test(value)) callback()
        else callback(new Error('密码须同时包含字母和数字'))
      },
      trigger: 'blur',
    },
  ],
  confirm_password: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    { validator: validatePass2, trigger: 'blur' },
  ],
}

const installing = ref(false)
const installProgress = ref(10)
const installResult = ref(null)
const resultText = computed(() =>
  installResult.value
    ? `超级管理员「${installResult.value.admin_username}」已创建，数据库：${installResult.value.db_type}`
    : '',
)

async function loadEnvironment() {
  envLoading.value = true
  try {
    const res = await getEnvironment(adminForm.storage_dir || undefined)
    Object.assign(env, res.data)
  } finally {
    envLoading.value = false
  }
}

function resetDbTested() {
  dbTested.value = false
}

function onDbTypeChange() {
  dbInputMode.value = 'form'
  resetDbTested()
}

function dbPayload() {
  if (dbForm.db_type !== 'sqlite' && dbInputMode.value === 'dsn') {
    return { database_uri: dsnUri.value.trim() }
  }
  const base = { db_type: dbForm.db_type }
  if (dbForm.db_type === 'sqlite') {
    base.database = dbForm.database || 'zhycloud.db'
  } else {
    base.host = dbForm.host
    base.port = dbForm.port
    base.database = dbForm.database
    base.username = dbForm.username
    base.password = dbForm.password
  }
  return base
}

async function handleTestDb() {
  if (dbForm.db_type !== 'sqlite' && dbInputMode.value === 'dsn' && !dsnUri.value.trim()) {
    ElMessage.warning('请先粘贴数据库连接字符串')
    return
  }
  dbTesting.value = true
  try {
    await testDatabase(dbPayload())
    dbTested.value = true
    ElMessage.success('数据库连接正常')
  } catch (e) {
    dbTested.value = false
  } finally {
    dbTesting.value = false
  }
}

async function handleSubmit() {
  if (!adminFormRef.value) return
  await adminFormRef.value.validate(async (valid) => {
    if (!valid) return
    if (!dbTested.value) {
      ElMessage.warning('请先完成数据库连接测试')
      active.value = 2
      return
    }
    active.value = 5
    installing.value = true
    installProgress.value = 45
    try {
      const payload = {
        ...dbPayload(),
        admin_username: adminForm.admin_username.trim(),
        admin_email: adminForm.admin_email.trim(),
        admin_password: adminForm.admin_password,
        department_drive_enabled: enableDepartment.value,
      }
      if (adminForm.storage_dir.trim()) {
        payload.storage_dir = adminForm.storage_dir.trim()
      }
      if (dbForm.redis_url.trim()) {
        payload.redis_url = dbForm.redis_url.trim()
      }
      const res = await install(payload)
      installProgress.value = 100
      installResult.value = res.data
    } catch (e) {
      active.value = 4
    } finally {
      installing.value = false
    }
  })
}

function goLogin() {
  // 安装后状态已变化，硬跳转以重新加载应用状态
  location.href = '/login'
}

function formatSize(bytes) {
  if (!bytes && bytes !== 0) return '-'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let n = bytes
  let i = 0
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024
    i++
  }
  return `${n.toFixed(1)} ${units[i]}`
}

/** 欢迎页点击确定：进入环境检测步骤并自动加载环境信息。 */
function enterSetup() {
  active.value = 1
  loadEnvironment()
}
</script>

<style scoped>
.form-tip {
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
}

.feature-checkbox {
  height: auto;
}

.feature-tip {
  margin-top: 6px;
}

.setup-wrapper {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  box-sizing: border-box;
  background: linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%);
}

.setup-card {
  width: 720px;
  max-width: 100%;
  border-radius: 12px;
}

.setup-header h2 {
  margin: 0 0 6px;
  color: #1e293b;
}

.setup-header .sub {
  margin: 0;
  color: #64748b;
  font-size: 13px;
}

.steps {
  margin: 20px 0 30px;
}

.step-pane {
  min-height: 320px;
  padding: 0 8px;
}

.step-alert {
  margin-top: 16px;
}

.step-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 28px;
}

.path-hint {
  margin-left: 10px;
  color: #94a3b8;
  font-size: 12px;
}

.tested-tag {
  margin-left: 12px;
}

.result-pane {
  display: flex;
  align-items: center;
  justify-content: center;
}

.welcome-pane {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 380px;
}

.welcome-content {
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.welcome-logo {
  font-size: 56px;
  color: #1e3a8a;
  margin-bottom: 8px;
}

.welcome-title {
  font-size: 26px;
  font-weight: 600;
  color: #1e293b;
  margin: 0 0 6px;
}

.welcome-version {
  color: #64748b;
  font-size: 14px;
  margin: 0;
}

.welcome-divider {
  width: 320px;
  max-width: 100%;
  margin: 18px 0;
}

.welcome-copyright {
  color: #475569;
  font-size: 13px;
  margin: 0 0 4px;
}

.welcome-license {
  color: #94a3b8;
  font-size: 12px;
  margin: 0;
}

.welcome-pane .step-actions {
  margin-top: 32px;
}
</style>
