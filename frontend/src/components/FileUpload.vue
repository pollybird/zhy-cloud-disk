<template>
  <el-upload
    ref="uploadRef"
    :show-file-list="false"
    :auto-upload="true"
    :multiple="true"
    :before-upload="beforeUpload"
    :http-request="customUpload"
    name="files"
  >
    <el-button type="primary">
      <el-icon><Upload /></el-icon>&nbsp;上传文件
    </el-button>

    <el-dialog
      v-model="dialogVisible"
      title="上传进度"
      width="520px"
      :close-on-click-modal="false"
      :before-close="onBeforeClose"
    >
      <div v-for="task in tasks" :key="task.uid" class="task">
        <div class="task-head">
          <span class="task-name" :title="task.name">{{ task.name }}</span>
          <el-tag :type="statusType[task.status]" size="small">
            {{ statusText[task.status] }}
          </el-tag>
        </div>
        <el-progress
          :percentage="task.progress"
          :status="task.status === 'error' ? 'exception' : (task.status === 'success' || task.status === 'skipped') ? 'success' : ''"
          :color="task.status === 'hashing' ? '#e6a23c' : undefined"
        />
        <div v-if="task.message" class="task-msg">{{ task.message }}</div>
      </div>
      <el-empty v-if="!tasks.length" description="等待上传" :image-size="60" />
      <template #footer>
        <el-button v-if="hasBusy" type="warning" @click="cancelAll">
          取消全部并关闭
        </el-button>
        <el-button v-else type="primary" @click="closeDialog">关闭</el-button>
      </template>
    </el-dialog>
  </el-upload>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { checkDuplicate, uploadFiles } from '../api/file'
import {
  shouldUseChunk,
  tryInstant,
  uploadInChunks,
} from '../utils/chunkUploader'

const props = defineProps({
  parentId: { type: [Number, null], default: null },
  // 1.1.0 部门网盘上传：传入部门 ID；为空表示个人空间
  departmentId: { type: [Number, null], default: null },
})
const emit = defineEmits(['uploaded'])

const dialogVisible = ref(false)
const tasks = ref([])
let uidSeq = 0
let hasSuccess = false
// 进行中的请求控制器和 Worker：uid -> { controller?, worker? }
const controllers = new Map()

const statusText = {
  hashing: '计算指纹',
  uploading: '上传中',
  instant: '秒传',
  success: '成功',
  error: '失败',
  canceled: '已取消',
  skipped: '已跳过',
}
const statusType = {
  hashing: 'warning',
  uploading: 'primary',
  instant: 'success',
  success: 'success',
  error: 'danger',
  canceled: 'info',
  skipped: 'info',
}

const hasBusy = computed(() =>
  tasks.value.some(
    (t) => ['uploading', 'hashing', 'instant'].includes(t.status),
  ),
)

function beforeUpload() {
  dialogVisible.value = true
  return true
}

/**
 * 用 Web Worker 分块计算文件 MD5。
 * 返回 Promise<{hash, error}>。
 */
function computeFileHash(file, task) {
  return new Promise((resolve) => {
    try {
      const worker = new Worker(
        new URL('../utils/hashWorker.js', import.meta.url),
        { type: 'module' },
      )
      controllers.set(task.uid, { worker })
      worker.onmessage = (e) => {
        const msg = e.data
        if (msg.type === 'progress') {
          task.progress = msg.progress
        } else if (msg.type === 'done') {
          worker.terminate()
          controllers.delete(task.uid)
          resolve({ hash: msg.hash, error: null })
        } else if (msg.type === 'error') {
          worker.terminate()
          controllers.delete(task.uid)
          resolve({ hash: null, error: msg.msg })
        }
      }
      worker.onerror = () => {
        worker.terminate()
        controllers.delete(task.uid)
        resolve({ hash: null, error: 'Worker 错误' })
      }
      worker.postMessage({ file })
    } catch (e) {
      resolve({ hash: null, error: '无法启动 Worker' })
    }
  })
}

/**
 * 执行实际上传（含进度回调）。
 */
async function doUpload(file, task, { mode = 'normal', fileHash = null, overwriteId = null } = {}) {
  const formData = new FormData()
  formData.append('files', file)
  if (props.parentId) {
    formData.append('parent_id', String(props.parentId))
  }
  if (props.departmentId) {
    formData.append('department_id', String(props.departmentId))
  }
  if (fileHash) {
    formData.append('file_hash', fileHash)
  }
  if (mode !== 'normal') {
    formData.append('mode', mode)
  }
  if (overwriteId) {
    formData.append('overwrite_id', String(overwriteId))
  }
  const controller = new AbortController()
  controllers.set(task.uid, { controller })
  task.status = 'uploading'
  task.progress = 0
  try {
    const res = await uploadFiles(
      formData,
      (p) => { task.progress = p },
      controller.signal,
    )
    const failed = res.data.failed || []
    if (failed.length) {
      task.status = 'error'
      task.progress = 100
      task.message = failed.map((f) => f.msg).join('；')
    } else {
      task.status = 'success'
      task.progress = 100
      hasSuccess = true
    }
  } catch (e) {
    task.status = e.canceled ? 'canceled' : 'error'
    task.message = e.canceled ? '' : e.msg || '上传失败'
  } finally {
    controllers.delete(task.uid)
  }
}

function isAbortError(e) {
  return Boolean(
    e?.canceled
    || e?.code === 'ERR_CANCELED'
    || e?.name === 'CanceledError',
  )
}

/**
 * 大文件分片上传（含断点续传、并发 3、单片重试 3）。
 */
async function doChunkedUpload(file, task, hash) {
  const controller = new AbortController()
  controllers.set(task.uid, { controller })
  task.status = 'uploading'
  task.progress = 0
  task.message = '分片上传（可断点续传）'
  try {
    await uploadInChunks({
      file,
      hash,
      parentId: props.parentId || null,
      departmentId: props.departmentId || null,
      onProgress: (p) => { task.progress = p },
      signal: controller.signal,
    })
    task.status = 'success'
    task.progress = 100
    task.message = ''
    hasSuccess = true
  } catch (e) {
    task.status = isAbortError(e) ? 'canceled' : 'error'
    task.message = isAbortError(e) ? '已取消，稍后可继续上传' : (e.msg || '分片上传失败')
  } finally {
    controllers.delete(task.uid)
  }
}

/**
 * 正常新文件（非覆盖）：先尝试跨用户秒传，未命中再按大小选择分片/整文件上传。
 * 秒传服务不可用时静默降级。
 */
async function doUploadOrInstant(file, task, hash) {
  try {
    task.status = 'instant'
    task.message = '检测秒传…'
    const r = await tryInstant({
      file,
      hash,
      parentId: props.parentId || null,
      departmentId: props.departmentId || null,
    })
    if (r.instant) {
      task.progress = 100
      if (r.skipped) {
        task.status = 'skipped'
        task.message = '内容一致，已跳过'
      } else {
        task.status = 'instant'
        task.message = '秒传成功（秒级完成）'
      }
      hasSuccess = true
      return
    }
  } catch (e) {
    if (isAbortError(e)) {
      task.status = 'canceled'
      return
    }
    // 秒传检测失败不影响正常上传
  }

  if (shouldUseChunk(file)) {
    await doChunkedUpload(file, task, hash)
  } else {
    await doUpload(file, task, { fileHash: hash })
  }
}

async function customUpload({ file }) {
  const task = reactive({
    uid: ++uidSeq,
    name: file.name,
    progress: 0,
    status: 'hashing',
    message: '',
  })
  tasks.value.push(task)

  // 1. 计算文件 MD5
  const { hash, error } = await computeFileHash(file, task)
  if (error) {
    // Worker 失败，降级为普通上传（无去重）
    await doUpload(file, task)
    return
  }

  // 2. 预检同名冲突
  try {
    const res = await checkDuplicate({
      parent_id: props.parentId || null,
      department_id: props.departmentId || null,
      file_name: file.name,
      file_hash: hash,
    })
    const action = res.data.action

    if (action === 'skip') {
      task.status = 'skipped'
      task.progress = 100
      task.message = '内容一致，已跳过'
      hasSuccess = true
      return
    }

    if (action === 'upload') {
      await doUpload(file, task, { fileHash: hash })
      return
    }

    // conflict：询问用户
    if (res.data.is_folder) {
      task.status = 'error'
      task.progress = 100
      task.message = '同名文件夹已存在，无法上传'
      return
    }

    const existing = res.data.existing
    const tip = res.data.hash_missing
      ? `同名文件「${existing.file_name}」已存在，但原文件未记录指纹，无法自动判断是否相同。`
      : `同名文件「${existing.file_name}」内容不同。`

    let choice
    try {
      choice = await ElMessageBox.confirm(
        `${tip}\n请选择操作方式：`,
        '文件冲突',
        {
          confirmButtonText: '覆盖原文件',
          cancelButtonText: '保留两者',
          distinguishCancelAndClose: true,
          type: 'warning',
        },
      )
    } catch (action) {
      if (action === 'cancel') {
        // 保留两者
        choice = 'coexist'
      } else {
        // close (X 按钮) → 取消
        task.status = 'canceled'
        return
      }
    }

    if (choice === 'confirm') {
      // 覆盖
      await doUpload(file, task, {
        mode: 'overwrite',
        fileHash: hash,
        overwriteId: existing.id,
      })
    } else {
      // 共存（服务端自动改名），同样可秒传/分片
      await doUploadOrInstant(file, task, hash)
    }
  } catch (e) {
    // 预检失败，降级为普通上传
    await doUpload(file, task)
  }
}

function cancelAll() {
  controllers.forEach((c) => {
    if (c.controller) c.controller.abort()
    if (c.worker) c.worker.terminate()
  })
  controllers.clear()
  tasks.value.forEach((t) => {
    if (t.status === 'uploading' || t.status === 'hashing') t.status = 'canceled'
  })
  dialogVisible.value = false
  finishClose()
}

async function onBeforeClose(done) {
  if (hasBusy.value) {
    try {
      await ElMessageBox.confirm(
        '仍有文件正在处理，关闭将取消这些任务，是否继续？',
        '提示',
        { type: 'warning', confirmButtonText: '取消并关闭', cancelButtonText: '继续等待' },
      )
    } catch (e) {
      return
    }
    cancelAll()
    return
  }
  done()
  finishClose()
}

function finishClose() {
  tasks.value = []
  if (hasSuccess) {
    hasSuccess = false
    emit('uploaded')
  }
}

function closeDialog() {
  dialogVisible.value = false
  finishClose()
}
</script>

<style scoped>
.task {
  margin-bottom: 16px;
}

.task-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.task-name {
  font-size: 13px;
  color: #334155;
  max-width: 380px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-msg {
  font-size: 12px;
  color: #dc2626;
  margin-top: 4px;
}
</style>
