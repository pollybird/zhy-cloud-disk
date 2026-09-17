<template>
  <el-card class="dept-files-card" v-loading="treeLoading">
    <div class="dept-layout">
      <!-- 左侧：可访问部门树 -->
      <div class="dept-aside">
        <div class="dept-aside-head">
          <span class="dept-aside-title">部门网盘</span>
          <el-button text circle size="small" @click="reloadAll">
            <el-icon><Refresh /></el-icon>
          </el-button>
        </div>
        <el-tree
          v-if="deptTree.length"
          ref="treeRef"
          :data="deptTree"
          :props="treeProps"
          node-key="id"
          default-expand-all
          highlight-current
          :expand-on-click-node="false"
          @node-click="onDeptClick"
        >
          <template #default="{ data }">
            <span class="dept-node">
              <el-icon class="dept-node-icon"><OfficeBuilding /></el-icon>
              <span class="dept-node-name" :title="data.name">{{ data.name }}</span>
              <el-tag
                size="small"
                :type="permTagType(data.my_permission)"
                effect="plain"
                class="dept-node-tag"
              >
                {{ permLabel(data.my_permission) }}
              </el-tag>
            </span>
          </template>
        </el-tree>
        <el-empty
          v-else
          :description="treeLoading ? '加载中' : '暂无可访问的部门网盘'"
          :image-size="70"
        />
      </div>

      <!-- 右侧：文件浏览 -->
      <div class="file-pane">
        <template v-if="selectedDeptId">
          <!-- 顶部工具栏 -->
          <div class="toolbar">
            <div class="left">
              <el-breadcrumb
                v-if="category === 'all' && !keyword"
                separator="/"
                class="crumb"
              >
                <el-breadcrumb-item @click="enterFolder(null)">
                  <span class="crumb-link">{{ selectedDept?.name || '部门根目录' }}</span>
                </el-breadcrumb-item>
                <el-breadcrumb-item
                  v-for="b in breadcrumb"
                  :key="b.id"
                  @click="enterFolder(b.id)"
                >
                  <span class="crumb-link">{{ b.file_name }}</span>
                </el-breadcrumb-item>
              </el-breadcrumb>
              <span v-else-if="keyword" class="category-title">
                搜索结果：{{ keyword }}
              </span>
              <span v-else class="category-title">{{ categoryLabel }}</span>
            </div>
            <div class="right">
              <span class="quota">
                部门空间：{{ formatSize(selectedDept?.used_storage) }} /
                {{ selectedDept?.storage_quota ? formatSize(selectedDept.storage_quota) : '不限' }}
              </span>
              <el-button
                v-if="writable"
                type="success"
                plain
                @click="createFolder"
              >
                <el-icon><FolderAdd /></el-icon>&nbsp;新建文件夹
              </el-button>
              <file-upload
                v-if="writable"
                :department-id="selectedDeptId"
                :parent-id="category === 'all' ? parentId : null"
                @uploaded="onUploaded"
              />
              <el-button circle @click="loadList">
                <el-icon><Refresh /></el-icon>
              </el-button>
            </div>
          </div>

          <!-- 只读提示 -->
          <el-alert
            v-if="!writable && category === 'all' && !keyword"
            title="当前仅有只读权限，可浏览与下载，不可上传或修改"
            type="info"
            :closable="false"
            show-icon
            class="readonly-tip"
          />

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
              :placeholder="`搜索 ${selectedDept?.name || '部门'} 文件`"
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
                  <el-tag
                    v-if="row.access === 'read_only'"
                    size="small"
                    type="info"
                    effect="plain"
                    class="row-perm-tag"
                  >
                    只读
                  </el-tag>
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
            <el-table-column label="操作" width="300" fixed="right">
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
                <template v-if="canWrite(row.access)">
                  <el-button link type="warning" @click="rename(row)">重命名</el-button>
                  <el-button link type="primary" @click="openMove(row)">移动</el-button>
                  <el-button link type="danger" @click="remove(row)">删除</el-button>
                </template>
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

          <move-dialog
            v-model="moveVisible"
            :node="activeNode"
            :department-id="selectedDeptId"
            @moved="loadList"
          />

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
        </template>

        <el-empty v-else description="请选择左侧部门" :image-size="100" class="empty-pane" />
      </div>
    </div>
  </el-card>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import FileUpload from '../../components/FileUpload.vue'
import MoveDialog from '../../components/MoveDialog.vue'
import PluginPreview from '../../components/PluginPreview.vue'
import { getDepartmentTree } from '../../api/department'
import {
  createFolder as apiCreateFolder,
  deleteFile,
  downloadFile,
  listFiles,
  renameFile,
} from '../../api/file'
import { formatDateTime, formatSize } from '../../utils/format'
import FileIcon from '../../components/FileIcon.vue'
import { canWrite, findDeptNode } from '../../utils/deptTree'

const route = useRoute()
const treeProps = { label: 'name', children: 'children' }

const treeRef = ref()
const treeLoading = ref(false)
const deptTree = ref([])
const selectedDeptId = ref(null)

const parentId = ref(null)
const category = ref('all')
const keyword = ref('')
const items = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(50)
const loading = ref(false)
const breadcrumb = ref([])
// 当前目录的有效权限：read_write / read_only / none
const containerAccess = ref('none')
const moveVisible = ref(false)
const previewVisible = ref(false)
const activeNode = ref({})

const selectedDept = computed(() => findDeptNode(deptTree.value, selectedDeptId.value))

// 分类 / 搜索模式下不允许上传与新建（与个人空间行为一致）
const writable = computed(
  () => canWrite(containerAccess.value) && category.value === 'all' && !keyword.value,
)

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

function permLabel(perm) {
  if (perm === 'read_write') return '读写'
  if (perm === 'read_only') return '只读'
  return '无权'
}

function permTagType(perm) {
  if (perm === 'read_write') return 'success'
  if (perm === 'read_only') return 'info'
  return 'danger'
}

/** 深度优先查找第一个可访问（非 none）的部门 id。 */
function firstReadableId(nodes) {
  for (const node of nodes || []) {
    if (node.my_permission && node.my_permission !== 'none') return node.id
    const child = firstReadableId(node.children)
    if (child) return child
  }
  return null
}

async function loadDeptTree(selectInitial = false) {
  treeLoading.value = true
  try {
    const res = await getDepartmentTree()
    deptTree.value = res.data || []
    if (selectInitial) {
      const queryId = route.query.dept_id ? Number(route.query.dept_id) : null
      let initial = null
      if (queryId && findDeptNode(deptTree.value, queryId)) {
        initial = queryId
      } else {
        initial = firstReadableId(deptTree.value)
      }
      if (initial) {
        selectedDeptId.value = initial
        treeRef.value?.setCurrentKey(initial)
        await loadList()
      } else {
        selectedDeptId.value = null
      }
    }
  } finally {
    treeLoading.value = false
  }
}

async function loadList() {
  if (!selectedDeptId.value) {
    items.value = []
    total.value = 0
    return
  }
  const seq = ++listSeq
  loading.value = true
  try {
    const params = {
      department_id: selectedDeptId.value,
      page: page.value,
      size: size.value,
    }
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
    containerAccess.value = res.data.access || 'none'
  } catch (e) {
    if (seq === listSeq) {
      items.value = []
      total.value = 0
      containerAccess.value = 'none'
    }
  } finally {
    if (seq === listSeq) loading.value = false
  }
}

async function reloadAll() {
  await loadDeptTree(false)
  if (selectedDeptId.value) await loadList()
}

function onDeptClick(data) {
  if (data.my_permission === 'none') {
    ElMessage.warning('您无权访问该部门网盘')
    treeRef.value?.setCurrentKey(selectedDeptId.value)
    return
  }
  selectDept(data.id)
}

function selectDept(id) {
  if (selectedDeptId.value === id) return
  selectedDeptId.value = id
  parentId.value = null
  category.value = 'all'
  keyword.value = ''
  page.value = 1
  loadList()
}

function enterFolder(id) {
  category.value = 'all'
  keyword.value = ''
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

function onCategoryChange() {
  page.value = 1
  loadList()
}

function onPageChange(p) {
  page.value = p
  loadList()
}

async function createFolder() {
  const { value } = await ElMessageBox.prompt('请输入文件夹名称', '新建文件夹', {
    confirmButtonText: '创建',
    cancelButtonText: '取消',
    inputPattern: /^[^/\\:*?"<>|]{1,255}$/,
    inputErrorMessage: '名称不合法（1-255 字符，不含 / \\ : * ? " < > |）',
  })
  await apiCreateFolder(parentId.value, value.trim(), selectedDeptId.value)
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
  await loadList()
  // 释放部门配额后刷新树节点上的空间数据
  loadDeptTree(false)
}

async function onUploaded() {
  await loadList()
  loadDeptTree(false)
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

onMounted(() => loadDeptTree(true))
</script>

<style scoped>
.dept-layout {
  display: flex;
  gap: 16px;
  min-height: 560px;
}

.dept-aside {
  width: 250px;
  flex-shrink: 0;
  border-right: 1px solid #e5e7eb;
  padding-right: 14px;
}

.dept-aside-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.dept-aside-title {
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
}

.dept-node {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 210px;
}

.dept-node-icon {
  color: #2563eb;
}

.dept-node-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dept-node-tag {
  flex-shrink: 0;
  transform: scale(0.9);
}

.file-pane {
  flex: 1;
  min-width: 0;
}

.empty-pane {
  margin-top: 120px;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
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

.readonly-tip {
  margin-bottom: 12px;
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

.row-perm-tag {
  transform: scale(0.9);
}

.pager {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
