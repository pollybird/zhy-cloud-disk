<template>
  <el-dialog
    :model-value="modelValue"
    title="分享文件"
    width="520px"
    :close-on-click-modal="false"
    @update:model-value="onVisible"
  >
    <!-- 创建表单 -->
    <div v-if="!created" class="share-form">
      <div class="file-line">
        <el-icon class="file-ico"><Document /></el-icon>
        <span class="file-name" :title="file.file_name">{{ file.file_name }}</span>
      </div>
      <el-form label-width="92px">
        <el-form-item label="有效期">
          <el-radio-group v-model="expireDays">
            <el-radio :value="0">永久</el-radio>
            <el-radio :value="1">1 天</el-radio>
            <el-radio :value="7">7 天</el-radio>
            <el-radio :value="30">30 天</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="访问密码">
          <el-input
            v-model="password"
            placeholder="留空为公开分享，填写后需凭密码访问"
            maxlength="32"
            clearable
          />
        </el-form-item>
      </el-form>
      <div class="dialog-actions">
        <el-button @click="onVisible(false)">取消</el-button>
        <el-button type="primary" :loading="submitting" :disabled="submitting" @click="handleCreate">
          创建分享
        </el-button>
      </div>
    </div>

    <!-- 创建结果 -->
    <div v-else class="share-result">
      <el-result icon="success" title="分享链接已生成" sub-title="链接有效期与密码见下方信息">
        <template #extra>
          <div class="result-box">
            <div class="row">
              <span class="lbl">分享链接</span>
              <el-input :model-value="link" readonly>
                <template #append>
                  <el-button @click="copy(link)">复制</el-button>
                </template>
              </el-input>
            </div>
            <div class="row" v-if="result.share_pwd">
              <span class="lbl">访问密码</span>
              <el-input :model-value="result.share_pwd" readonly>
                <template #append>
                  <el-button @click="copy(result.share_pwd)">复制</el-button>
                </template>
              </el-input>
            </div>
            <div class="row tip">
              {{ result.expire_time ? '链接将于设定的到期时间自动失效' : '该链接永久有效，可在“我的分享”中随时取消' }}
            </div>
          </div>
          <el-button @click="onVisible(false)">关闭</el-button>
          <el-button type="primary" @click="goMyShares">前往我的分享</el-button>
        </template>
      </el-result>
    </div>
  </el-dialog>
</template>

<script setup>
import { reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createShare, sharePageUrl } from '../api/share'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  file: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['update:modelValue', 'created'])

const router = useRouter()
const expireDays = ref(0)
const password = ref('')
const submitting = ref(false)
const created = ref(false)
const result = reactive({ share_code: '', share_pwd: '', expire_time: null })
const link = ref('')

watch(
  () => props.modelValue,
  (visible) => {
    if (visible) reset()
  },
)

function reset() {
  expireDays.value = 0
  password.value = ''
  submitting.value = false
  created.value = false
  result.share_code = ''
  result.share_pwd = ''
  result.expire_time = null
  link.value = ''
}

async function handleCreate() {
  submitting.value = true
  try {
    const res = await createShare({
      file_id: props.file.id,
      expire_days: expireDays.value,
      password: password.value.trim() || null,
    })
    Object.assign(result, {
      share_code: res.data.share_code,
      share_pwd: password.value.trim(),
      expire_time: res.data.expire_time,
    })
    link.value = sharePageUrl(res.data.share_code)
    created.value = true
    emit('created')
  } finally {
    submitting.value = false
  }
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text)
  } catch (e) {
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    ta.remove()
  }
  ElMessage.success('已复制到剪贴板')
}

function goMyShares() {
  onVisible(false)
  router.push('/shares')
}

function onVisible(v) {
  emit('update:modelValue', v)
}
</script>

<style scoped>
.file-line {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  background: #f8fafc;
  border-radius: 8px;
  margin-bottom: 16px;
}

.file-ico {
  color: #3b82f6;
  font-size: 18px;
}

.file-name {
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.result-box {
  width: 100%;
  text-align: left;
  margin-bottom: 8px;
}

.result-box .row {
  display: flex;
  align-items: center;
  margin-bottom: 12px;
}

.result-box .lbl {
  width: 72px;
  flex-shrink: 0;
  color: #64748b;
  font-size: 13px;
}

.result-box .tip {
  font-size: 12px;
  color: #94a3b8;
  padding-left: 72px;
}
</style>
