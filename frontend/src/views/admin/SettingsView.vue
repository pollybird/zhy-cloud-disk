<template>
  <div v-loading="loading" class="settings-wrap">
    <!-- 注册与安全 -->
    <el-card class="block">
      <template #header><span class="block-title">注册与安全</span></template>
      <el-form label-width="160px" class="form">
        <el-form-item label="公开注册">
          <el-switch v-model="form.allow_register" inline-prompt active-text="开" inactive-text="关" />
          <span class="hint">
            开启后游客可自行注册账号（普通角色、默认配额）；关闭后仅管理员可添加账号
          </span>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 回收站与历史版本 -->
    <el-card class="block">
      <template #header><span class="block-title">回收站与历史版本</span></template>
      <el-form label-width="160px" class="form">
        <el-form-item label="回收站">
          <el-switch v-model="form.trash_enabled" inline-prompt active-text="开" inactive-text="关" />
          <span class="hint">关闭后删除文件将直接释放存储空间；关闭不会清空回收站中的存量文件</span>
        </el-form-item>
        <el-form-item label="回收站保留天数">
          <el-input-number v-model="form.trash_retention_days" :min="1" :max="365" />
          <span class="hint">天，到期后系统自动彻底删除</span>
        </el-form-item>
        <el-form-item label="历史版本">
          <el-switch v-model="form.version_enabled" inline-prompt active-text="开" inactive-text="关" />
          <span class="hint">关闭后覆盖上传不再保存历史版本；已保存的版本仍可访问（管理员关闭期间不能恢复版本）</span>
        </el-form-item>
        <el-form-item label="每文件保留版本数">
          <el-input-number v-model="form.version_max_count" :min="1" :max="100" />
          <span class="hint">个，超出后自动淘汰最旧版本</span>
        </el-form-item>
        <el-form-item label="版本保留天数">
          <el-input-number v-model="form.version_retention_days" :min="1" :max="365" />
          <span class="hint">天</span>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 备份恢复 -->
    <el-card class="block">
      <template #header><span class="block-title">备份与恢复</span></template>
      <el-form label-width="160px" class="form">
        <el-form-item label="每日自动备份">
          <el-switch v-model="form.backup_enabled" inline-prompt active-text="开" inactive-text="关" />
          <span class="hint">每天定点自动备份数据库与系统配置（不含文件实体）</span>
        </el-form-item>
        <el-form-item label="备份时间">
          <el-select v-model="form.backup_hour" style="width: 110px">
            <el-option v-for="h in 24" :key="h - 1" :label="`${String(h - 1).padStart(2, '0')}:17`" :value="h - 1" />
          </el-select>
          <span class="hint">在该小时的第 17 分钟执行</span>
        </el-form-item>
        <el-form-item label="自动备份保留份数">
          <el-input-number v-model="form.backup_keep_count" :min="1" :max="100" />
          <span class="hint">份，超出后自动清理最旧的定时备份（手动备份不参与清理）</span>
        </el-form-item>

        <el-divider content-position="left">备份目标</el-divider>
        <el-form-item label="备份位置">
          <el-radio-group v-model="form.backup_target">
            <el-radio value="local">本地服务器</el-radio>
            <el-radio value="remote">远端服务器（推荐 SFTP）</el-radio>
          </el-radio-group>
        </el-form-item>

        <template v-if="form.backup_target === 'remote'">
          <el-form-item label="传输协议">
            <el-radio-group v-model="form.backup_protocol" @change="onProtocolChange">
              <el-radio value="sftp">SFTP</el-radio>
              <el-radio value="ftp">FTP</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="服务器地址">
            <el-input v-model="form.backup_host" placeholder="例如 192.168.1.10 或 backup.example.com" style="max-width: 360px" />
          </el-form-item>
          <el-form-item label="端口">
            <el-input-number v-model="form.backup_port" :min="1" :max="65535" />
            <span class="hint">SFTP 默认 22，FTP 默认 21</span>
          </el-form-item>
          <el-form-item label="用户名">
            <el-input v-model="form.backup_username" placeholder="登录用户名（匿名 FTP 可留空）" style="max-width: 360px" />
          </el-form-item>
          <el-form-item>
            <template #label>
              密码
              <el-tag v-if="hasPassword && !passwordTouched" size="small" type="success" effect="plain" class="pwd-tag">
                已配置
              </el-tag>
            </template>
            <el-input
              v-model="form.backup_password"
              type="password"
              show-password
              :placeholder="hasPassword ? '留空表示不修改已保存的密码' : '登录密码（匿名 FTP 可留空）'"
              style="max-width: 360px"
              @input="passwordTouched = true"
            />
          </el-form-item>
          <el-form-item label="远端目录">
            <el-input v-model="form.backup_remote_dir" placeholder="/zhy-backups" style="max-width: 360px" />
            <span class="hint">不存在时将尝试逐级创建</span>
          </el-form-item>
          <el-form-item>
            <el-button :loading="testing" @click="onTestConnection">
              <el-icon><Connection /></el-icon>&nbsp;测试连接
            </el-button>
            <span class="hint">仅测试当前填写的配置，不会保存</span>
          </el-form-item>
        </template>
      </el-form>
    </el-card>

    <div class="footer-bar">
      <el-button type="primary" :loading="saving" @click="onSave">保存设置</el-button>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getAdminSettings, updateAdminSettings } from '../../api/user'
import { testBackupConnection } from '../../api/admin'

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const hasPassword = ref(false)
const passwordTouched = ref(false)

const defaults = () => ({
  allow_register: false,
  trash_enabled: true,
  version_enabled: true,
  trash_retention_days: 30,
  version_max_count: 10,
  version_retention_days: 30,
  backup_enabled: false,
  backup_hour: 3,
  backup_keep_count: 7,
  backup_target: 'local',
  backup_protocol: 'sftp',
  backup_host: '',
  backup_port: 22,
  backup_username: '',
  backup_password: '',
  backup_remote_dir: '/zhy-backups',
})

const form = reactive(defaults())

function applySettings(data) {
  Object.assign(form, {
    allow_register: !!data.allow_register,
    trash_enabled: data.trash_enabled !== false,
    version_enabled: data.version_enabled !== false,
    trash_retention_days: data.trash_retention_days ?? 30,
    version_max_count: data.version_max_count ?? 10,
    version_retention_days: data.version_retention_days ?? 30,
    backup_enabled: !!data.backup_enabled,
    backup_hour: data.backup_hour ?? 3,
    backup_keep_count: data.backup_keep_count ?? 7,
    backup_target: data.backup_target || 'local',
    backup_protocol: data.backup_protocol || 'sftp',
    backup_host: data.backup_host || '',
    backup_port: data.backup_port || (data.backup_protocol === 'ftp' ? 21 : 22),
    backup_username: data.backup_username || '',
    backup_password: '',
    backup_remote_dir: data.backup_remote_dir || '/zhy-backups',
  })
  hasPassword.value = !!data.backup_has_password
  passwordTouched.value = false
}

async function load() {
  loading.value = true
  try {
    const res = await getAdminSettings()
    applySettings(res.data)
  } finally {
    loading.value = false
  }
}

function onProtocolChange(protocol) {
  // 仅在端口仍是另一协议的默认值时自动切换，避免覆盖用户自定义端口
  if (protocol === 'ftp' && Number(form.backup_port) === 22) form.backup_port = 21
  if (protocol === 'sftp' && Number(form.backup_port) === 21) form.backup_port = 22
}

async function onTestConnection() {
  testing.value = true
  try {
    const res = await testBackupConnection({
      backup_protocol: form.backup_protocol,
      backup_host: form.backup_host,
      backup_port: form.backup_port,
      backup_username: form.backup_username,
      // 空密码不下发，后端使用已保存密码（未保存则匿名）
      backup_password: form.backup_password || undefined,
      backup_remote_dir: form.backup_remote_dir,
    })
    ElMessage.success(res.msg || '连接成功')
  } finally {
    testing.value = false
  }
}

async function onSave() {
  saving.value = true
  try {
    const payload = { ...form }
    // 密码留空 = 不修改：直接删除该字段
    if (!payload.backup_password) delete payload.backup_password
    const res = await updateAdminSettings(payload)
    applySettings(res.data)
    ElMessage.success('设置已保存')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.settings-wrap {
  max-width: 900px;
}

.block {
  margin-bottom: 16px;
}

.block-title {
  font-weight: 600;
  color: #1e293b;
}

.form {
  max-width: 760px;
}

.hint {
  margin-left: 12px;
  font-size: 12px;
  color: #94a3b8;
}

.pwd-tag {
  margin-left: 6px;
  transform: scale(0.9);
}

.footer-bar {
  text-align: right;
}
</style>
