<template>
  <div class="plugin-preview">
    <div v-if="loading" class="placeholder" v-loading="true" element-loading-text="加载预览…"
      element-loading-background="transparent" />

    <template v-else>
      <!-- 图片 -->
      <img
        v-if="renderType === 'image'"
        :src="src"
        class="preview-image"
        :alt="file.file_name"
      />
      <!-- 视频 -->
      <video
        v-else-if="renderType === 'video'"
        :src="src"
        controls
        preload="metadata"
        class="preview-video"
      />
      <!-- PDF -->
      <iframe v-else-if="renderType === 'pdf'" :src="src" class="preview-frame" />
      <!-- 纯文本 -->
      <pre v-else-if="renderType === 'text'" class="preview-text">{{ textContent }}</pre>

      <!-- 无可用预览插件 -->
      <div v-else class="placeholder">
        <el-icon :size="30"><View /></el-icon>
        <span>{{ noneText }}</span>
      </div>
    </template>

    <div v-if="pluginName && renderType !== 'none'" class="plugin-sign">
      预览由插件 {{ pluginName }} 提供
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { authCheck, availablePlugins, fetchStream, pluginStreamUrl } from '../api/plugin'

const props = defineProps({
  /** owner：归属用户（JWT 鉴权）；share：分享访客（code+token） */
  mode: { type: String, default: 'owner' },
  /** { id, file_name, file_suffix } */
  file: { type: Object, required: true },
  /** share 模式必填 */
  code: { type: String, default: '' },
  /** share 模式必填 */
  token: { type: String, default: '' },
})

const emit = defineEmits(['loaded', 'no-plugin'])

const loading = ref(true)
const renderType = ref('none')
const src = ref('')
const textContent = ref('')
const pluginName = ref('')
const noneText = ref('该文件类型暂不支持在线预览')

let objectUrl = ''

function effectivePreviewType(plugin, suffix) {
  // document-preview 等插件可用 ext_preview 按后缀细化渲染类型
  const s = (suffix || '').toLowerCase()
  if (plugin.ext_preview && plugin.ext_preview[s]) return plugin.ext_preview[s]
  return plugin.preview_type || 'none'
}

async function loadPlugins() {
  if (props.mode === 'share') {
    const res = await authCheck({ code: props.code, token: props.token })
    return res.data.plugins || []
  }
  const res = await availablePlugins(props.file.file_suffix)
  return res.data.items || []
}

async function buildSrc(plugin) {
  const suffix = props.file.file_suffix || ''
  const type = effectivePreviewType(plugin, suffix)

  // 文本渲染：两种模式都需拉取内容解码
  if (type === 'text') {
    if (props.mode === 'share') {
      // 分享访客：直链含访问令牌，无需请求头
      const resp = await fetch(
        pluginStreamUrl(props.code, props.token) + `&plugin=${plugin.name}`
      )
      if (!resp.ok) throw new Error('stream fetch failed')
      textContent.value = await resp.text()
    } else {
      // 归属用户：携带 JWT 的 blob 拉取
      const res = await fetchStream({ id: props.file.id, plugin: plugin.name })
      textContent.value = await res.data.text()
    }
    return
  }

  if (props.mode === 'share') {
    // 分享访客：直链可被 img/video/iframe 直接引用
    src.value = pluginStreamUrl(props.code, props.token) + `&plugin=${plugin.name}`
    return
  }
  // 归属用户：携带 JWT 以 blob 拉取（img/video/iframe 无法注入请求头）
  const res = await fetchStream({ id: props.file.id, plugin: plugin.name })
  objectUrl = URL.createObjectURL(res.data)
  src.value = objectUrl
}

async function load() {
  loading.value = true
  renderType.value = 'none'
  src.value = ''
  textContent.value = ''
  pluginName.value = ''
  try {
    const plugins = await loadPlugins()
    const suffix = props.file.file_suffix || ''
    const plugin = plugins.find((p) => effectivePreviewType(p, suffix) !== 'none') || null
    if (!plugin) {
      noneText.value = `暂无支持 .${suffix} 在线预览的插件，可下载查看`
      emit('no-plugin')
      return
    }
    pluginName.value = plugin.name
    renderType.value = effectivePreviewType(plugin, suffix)
    await buildSrc(plugin)
    emit('loaded', plugin)
  } catch (e) {
    renderType.value = 'none'
    noneText.value = e?.msg || '预览加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

onMounted(load)

onBeforeUnmount(() => {
  if (objectUrl) {
    URL.revokeObjectURL(objectUrl)
    objectUrl = ''
  }
})
</script>

<style scoped>
.plugin-preview {
  min-height: 200px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.placeholder {
  min-height: 160px;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #94a3b8;
  font-size: 13px;
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
  border-radius: 10px;
}

.preview-image {
  max-width: 100%;
  max-height: 60vh;
  object-fit: contain;
  border-radius: 8px;
  background: #f1f5f9;
}

.preview-video {
  width: 100%;
  max-height: 60vh;
  border-radius: 8px;
  background: #000;
}

.preview-frame {
  width: 100%;
  height: 60vh;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.preview-text {
  width: 100%;
  max-height: 60vh;
  overflow: auto;
  margin: 0;
  padding: 14px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.7;
  color: #334155;
  white-space: pre-wrap;
  word-break: break-all;
  box-sizing: border-box;
}

.plugin-sign {
  margin-top: 10px;
  font-size: 12px;
  color: #94a3b8;
}
</style>
