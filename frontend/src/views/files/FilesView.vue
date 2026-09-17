<template>
  <el-card>
    <!-- 顶部工具栏 -->
    <div class="toolbar">
      <div class="left">
        <el-breadcrumb v-if="category === 'all' && !keyword" separator="/" class="crumb">
          <el-breadcrumb-item @click="enterFolder(null)">
            <span class="crumb-link">全部文件</span>
          </el-breadcrumb-item>
          <el-breadcrumb-item
            v-for="b in breadcrumb"
            :key="b.id"
            @click="enterFolder(b.id)"
          >
            <span class="crumb-link">{{ b.file_name }}</span>
          </el-breadcrumb-item>
        </el-breadcrumb>
        <span v-else-if="keyword" class="category-title">搜索结果：{{ keyword }}</span>
        <span v-else class="category-title">{{ categoryLabel }}</span>
      </div>
      <div class="right">
        <span class="quota">
          空间：{{ formatSize(user.used_storage) }} / {{ formatSize(user.total_storage) }}
        </span>
        <el-button type="success" plain @click="createFolder">
          <el-icon><FolderAdd /></el-icon>&nbsp;新建文件夹
        </el-button>
        <file-upload :parent-id="category === 'all' ? parentId : null" @uploaded="loadAll" />
        <el-button circle @click="loadAll">
          <el-icon><Refresh /></el-icon>
        </el-button>
      </div>
    </div>

    <!-- 分类与搜索 -->
    <div class="filters">
      <el-radio-group v-model="category" size="default" @change="onCategoryChange">
        <el-radio-button value="all">全部</el-radio-button>
        <el-radio-button value="image">图片</el-radio-button>
        <el-radio-button value="video">视频</el-radio-button>
        <el-radio-button value="document">文档</el-radio-button>
        <el-radio-button value="audio">音频</el-radio-button>
        <el-radio-button value="archive">压缩包</el-radio-button>
      </el-radio-group>
      <el-input
        v-model="keyword"
        placeholder="搜索我的全部文件"
        clearable
        style="width: 240px"
        @keyup.enter="loadList"
        @clear="loadList"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
    </div>

    <!-- 文件表格 -->
    <el-table
      :data="items"
      v-loading="loading"
      border
      stripe
      @row-dblclick="onRowDblclick"
    >
      <el-table-column label="名称" min-width="260">
        <template #default="{ row }">
          <span
            class="name-cell"
            :class="{ link: row.is_folder }"
            @click.stop="openRow(row)"
          >
            <FileIcon class="file-icon" :row="row" :size="20" />
            <span>{{ row.file_name }}</span>
          </span>
        </template>
      </el-table-column>
      <el-table-column label="大小" width="120">
        <template #default="{ row }">
          {{ row.is_folder ? '-' : formatSize(row.file_size) }}
        </template>
      </el-table-column>
      <el-table-column prop="file_suffix" label="类型" width="100">
        <template #default="{ row }">
          {{ row.is_folder ? '文件夹' : row.file_suffix || '未知' }}
        </template>
      </el-table-column>
      <el-table-column label="上传时间" width="170">
        <template #default="{ row }">{{ formatDateTime(row.upload_time) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="380" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="!row.is_folder"
            link
            type="primary"
            @click="openPreview(row)"
          >
            预览
          </el-button>
          <el-button
            v-if="!row.is_folder"
            link
            type="primary"
            @click="download(row)"
          >
            下载
          </el-button>
          <el-button
            v-if="!row.is_folder"
            link
            type="success"
            @click="openShare(row)"
          >
            分享
          </el-button>
          <el-button link type="warning" @click="rename(row)">重命名</el-button>
          <el-button link type="primary" @click="openMove(row)">移动</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
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

    <move-dialog v-model="moveVisible" :node="activeNode" @moved="loadAll" />
    <share-dialog v-model="shareVisible" :file="activeNode" />

    <!-- 插件预览弹窗 -->
    <el-dialog
      v-model="previewVisible"
      :title="activeNode.file_name || '文件预览'"
      width="760px"
      top="6vh"
      destroy-on-close
    >
      <plugin-preview v-if="previewVisible" mode="owner" :file="activeNode" />
    </el-dialog>
  </el-card>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import FileUpload from '../../components/FileUpload.vue'
import MoveDialog from '../../components/MoveDialog.vue'
import PluginPreview from '../../components/PluginPreview.vue'
import ShareDialog from '../../components/ShareDialog.vue'
import {
  createFolder as apiCreateFolder,
  deleteFile,
  downloadFile,
  listFiles,
  renameFile,
} from '../../api/file'
import { useUserStore } from '../../stores/user'
import { formatDateTime, formatSize } from '../../utils/format'
import FileIcon from '../../components/FileIcon.vue'

const userStore = useUserStore()
const user = computed(() => userStore.user || {})

const parentId = ref(null)
const category = ref('all')
const keyword = ref('')
const items = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(50)
const loading = ref(false)
const breadcrumb = ref([])
const moveVisible = ref(false)
const shareVisible = ref(false)
const previewVisible = ref(false)
const activeNode = ref({})

const categoryLabels = {
  all: '全部文件',
  image: '图片',
  video: '视频',
  document: '文档',
  audio: '音频',
  archive: '压缩包',
}
const categoryLabel = computed(() => categoryLabels[category.value])

// 列表请求序号，防止快速切换目录时响应乱序覆盖
let listSeq = 0

async function loadList() {
  // 序号保护：快速切换目录时，丢弃过期响应，避免旧数据覆盖新视图
  const seq = ++listSeq
  loading.value = true
  try {
    const params = { page: page.value, size: size.value }
    if (category.value !== 'all') {
      params.category = category.value
    } else {
      if (parentId.value) params.parent_id = parentId.value
    }
    if (keyword.value.trim()) params.keyword = keyword.value.trim()
    const res = await listFiles(params)
    if (seq !== listSeq) return
    items.value = res.data.items
    total.value = res.data.total
    breadcrumb.value = res.data.breadcrumb || []
  } finally {
    if (seq === listSeq) loading.value = false
  }
}

async function loadAll() {
  await Promise.all([loadList(), userStore.fetchInfo().catch(() => {})])
}

function onPageChange(p) {
  page.value = p
  loadList()
}

function onCategoryChange() {
  page.value = 1
  loadList()
}

function enterFolder(id) {
  category.value = 'all'
  parentId.value = id
  page.value = 1
  loadList()
}

function openRow(row) {
  if (row.is_folder) enterFolder(row.id)
}

function onRowDblclick(row) {
  if (row.is_folder) enterFolder(row.id)
  else download(row)
}

async function createFolder() {
  const { value } = await ElMessageBox.prompt('请输入文件夹名称', '新建文件夹', {
    confirmButtonText: '创建',
    cancelButtonText: '取消',
    inputPattern: /^[^/\\:*?"<>|]{1,255}$/,
    inputErrorMessage: '名称不合法（1-255 字符，不含 / \\ : * ? " < > |）',
  })
  await apiCreateFolder(category === 'all' ? parentId.value : null, value.trim())
  ElMessage.success('创建成功')
  loadList()
}

async function rename(row) {
  const { value } = await ElMessageBox.prompt('请输入新名称', '重命名', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    inputValue: row.file_name,
    inputPattern: /^[^/\\:*?"<>|]{1,255}$/,
    inputErrorMessage: '名称不合法（1-255 字符，不含 / \\ : * ? " < > |）',
  })
  await renameFile(row.id, value.trim())
  ElMessage.success('重命名成功')
  loadList()
}

function openMove(row) {
  activeNode.value = row
  moveVisible.value = true
}

function openShare(row) {
  activeNode.value = row
  shareVisible.value = true
}

function openPreview(row) {
  activeNode.value = row
  previewVisible.value = true
}

async function remove(row) {
  const tip = row.is_folder
    ? `文件夹「${row.file_name}」及其内全部内容将被删除，且不可恢复`
    : `文件「${row.file_name}」将被删除，且不可恢复`
  await ElMessageBox.confirm(tip, '删除确认', {
    type: 'warning',
    confirmButtonText: '删除',
    cancelButtonText: '取消',
  })
  await deleteFile(row.id)
  ElMessage.success('删除成功')
  loadAll()
}

async function download(row) {
  const response = await downloadFile(row.id)
  const disposition = response.headers['content-disposition'] || ''
  let name = row.file_name
  const star = /filename\*=UTF-8''(.+)$/i.exec(disposition)
  if (star) {
    name = decodeURIComponent(star[1])
  } else {
    const plain = /filename="?([^";]+)"?/i.exec(disposition)
    if (plain) name = plain[1]
  }
  const url = URL.createObjectURL(response.data)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

onMounted(loadAll)
</script>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  gap: 12px;
  flex-wrap: wrap;
}

.right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.quota {
  font-size: 12px;
  color: #64748b;
  white-space: nowrap;
}

.crumb {
  font-size: 15px;
}

.crumb-link {
  cursor: pointer;
  color: #2563eb;
}

.category-title {
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
}

.filters {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  gap: 12px;
  flex-wrap: wrap;
}

.name-cell {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.file-icon {
  font-size: 18px;
}

.link {
  cursor: pointer;
  color: #1e293b;
}

.link:hover {
  color: #2563eb;
}

.link:hover .file-icon {
  transform: scale(1.1);
}

.pager {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
