<template>
  <div class="access-wrapper">
    <div class="brand">钟毓私有云盘 · 文件分享</div>

    <el-card class="access-card" v-loading="loading">
      <!-- 失效提示 -->
      <el-result
        v-if="state === 'invalid'"
        icon="error"
        :title="errorTitle"
        :sub-title="errorSub"
      >
        <template #extra>
          <el-button type="primary" @click="goHome">返回首页</el-button>
        </template>
      </el-result>

      <!-- 密码校验 -->
      <div v-else-if="state === 'password'" class="pane">
        <div class="file-head">
          <el-icon class="file-ico"><Lock /></el-icon>
          <div>
            <div class="file-name">{{ info.file.file_name }}</div>
            <div class="file-meta">该分享已加密，请输入访问密码</div>
          </div>
        </div>
        <el-form @submit.prevent="handleVerify">
          <el-alert
            v-if="pwdError"
            :title="pwdError"
            type="error"
            show-icon
            :closable="false"
            class="pwd-alert"
          />
          <el-input
            v-model="password"
            type="password"
            show-password
            placeholder="访问密码"
            size="large"
            clearable
            @input="pwdError = ''"
            @keyup.enter="handleVerify"
          />
          <el-button
            type="primary"
            size="large"
            class="submit"
            :loading="verifying"
            @click="handleVerify"
          >
            验证并查看
          </el-button>
        </el-form>
        <div class="foot">
          <span>浏览 {{ info.view_count }} 次</span>
        </div>
      </div>

      <!-- 文件信息 + 下载 -->
      <div v-else-if="state === 'ready'" class="pane">
        <div class="file-head">
          <el-icon class="file-ico" :style="{ color: iconColor }">
            <component :is="iconComp" />
          </el-icon>
          <div class="file-info">
            <div class="file-name">{{ info.file.file_name }}</div>
            <div class="file-meta">
              {{ formatSize(info.file.file_size) }} · 浏览 {{ info.view_count }} 次
              <template v-if="info.expire_time"> · {{ formatDateTime(info.expire_time) }} 到期</template>
            </div>
          </div>
        </div>

        <!-- 预览插件挂载点：按后缀加载已启用插件注入预览视图 -->
        <div class="preview-mount">
          <plugin-preview
            v-if="token"
            mode="share"
            :code="route.params.code"
            :token="token"
            :file="{ file_name: info.file.file_name, file_suffix: info.file.file_suffix }"
          />
        </div>

        <el-button type="primary" size="large" class="submit" @click="handleDownload">
          <el-icon><Download /></el-icon>&nbsp;下载文件
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getShareInfo, shareDownloadUrl, verifySharePassword } from '../../api/share'
import PluginPreview from '../../components/PluginPreview.vue'
import { formatSize, formatDateTime } from '../../utils/format'

const route = useRoute()
const router = useRouter()

const loading = ref(true)
const verifying = ref(false)
const state = ref('loading') // loading/password/ready/invalid
const info = ref(null)
const token = ref('')
const password = ref('')
const pwdError = ref('')
const errorTitle = ref('分享无法访问')
const errorSub = ref('')

const ERROR_MAP = {
  4101: ['链接无效', '分享不存在或已被删除，请向分享者确认链接'],
  4102: ['分享已过期', '该分享超过了设定的有效期'],
  4103: ['分享已取消', '分享者已取消该分享，链接不再可用'],
  4107: ['文件已删除', '分享对应的源文件已被删除'],
}

const iconComp = computed(() => {
  const map = {
    image: 'Picture',
    video: 'VideoPlay',
    document: 'Document',
    audio: 'Headset',
    archive: 'Files',
  }
  return map[categoryOf(info.value?.file.file_suffix)] || 'Document'
})
const iconColor = computed(() => {
  const map = {
    image: '#10b981',
    video: '#ef4444',
    document: '#3b82f6',
    audio: '#8b5cf6',
    archive: '#64748b',
  }
  return map[categoryOf(info.value?.file.file_suffix)] || '#3b82f6'
})

function categoryOf(suffix) {
  const s = (suffix || '').toLowerCase()
  const table = {
    jpg: 'image', jpeg: 'image', png: 'image', gif: 'image', webp: 'image', bmp: 'image',
    mp4: 'video', flv: 'video', mov: 'video', avi: 'video', mkv: 'video', webm: 'video',
    pdf: 'document', doc: 'document', docx: 'document', xls: 'document',
    xlsx: 'document', txt: 'document', ppt: 'document', pptx: 'document',
    mp3: 'audio', wav: 'audio', flac: 'audio', aac: 'audio', ogg: 'audio', m4a: 'audio',
    zip: 'archive', rar: 'archive', '7z': 'archive', tar: 'archive', gz: 'archive',
  }
  return table[s] || 'other'
}

async function loadInfo() {
  loading.value = true
  try {
    const res = await getShareInfo(route.params.code)
    info.value = res.data
    if (res.data.need_password) {
      state.value = 'password'
    } else {
      token.value = res.data.token
      state.value = 'ready'
    }
  } catch (e) {
    const code = e?.code
    const mapped = ERROR_MAP[code]
    errorTitle.value = mapped ? mapped[0] : '分享无法访问'
    errorSub.value = mapped ? mapped[1] : (e?.msg || '请稍后再试或联系分享者')
    state.value = 'invalid'
  } finally {
    loading.value = false
  }
}

async function handleVerify() {
  if (!password.value) return
  verifying.value = true
  pwdError.value = ''
  try {
    const res = await verifySharePassword(route.params.code, password.value)
    token.value = res.data.token
    state.value = 'ready'
  } catch (e) {
    if (e?.code === 4106) {
      pwdError.value = e.msg || '尝试过于频繁，请稍后再试'
    } else {
      pwdError.value = '访问密码错误，请重新输入'
    }
  } finally {
    verifying.value = false
  }
}

function handleDownload() {
  // 直链跳转触发浏览器附件下载，匿名令牌 10 分钟内有效
  window.location.href = shareDownloadUrl(route.params.code, token.value)
}

function goHome() {
  router.push('/login')
}

onMounted(loadInfo)
</script>

<style scoped>
.access-wrapper {
  min-height: 100vh;
  background: linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%);
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 64px 20px;
  box-sizing: border-box;
}

.brand {
  color: #e2e8f0;
  font-size: 20px;
  font-weight: 600;
  margin-bottom: 28px;
  letter-spacing: 2px;
}

.access-card {
  width: 520px;
  max-width: 100%;
  border-radius: 14px;
}

.pane {
  padding: 8px 4px;
}

.file-head {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 22px;
}

.file-ico {
  font-size: 40px;
  color: #3b82f6;
}

.file-name {
  font-size: 17px;
  font-weight: 600;
  color: #1e293b;
  word-break: break-all;
}

.file-meta {
  font-size: 13px;
  color: #94a3b8;
  margin-top: 4px;
}

.submit {
  width: 100%;
  margin-top: 16px;
}

.pwd-alert {
  margin-bottom: 12px;
}

.foot {
  margin-top: 18px;
  text-align: center;
  font-size: 12px;
  color: #94a3b8;
}

.preview-mount {
  margin-bottom: 18px;
}
</style>
