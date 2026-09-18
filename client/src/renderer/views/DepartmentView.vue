<template>
  <div class="dept-container" @dragenter="onDragEnter" @dragover.prevent @dragleave="onDragLeave" @drop="onDrop">
    <el-card shadow="always" class="dept-card">
      <template #header>
        <div class="header">
          <div class="header-left">
            <el-button link @click="router.push('/')">
              <el-icon><ArrowLeft /></el-icon>&nbsp;返回
            </el-button>
            <span class="title">部门网盘</span>
            <el-tag v-if="selectedDept" size="small" :type="permTagType(selectedDept.my_permission)">
              {{ permLabel(selectedDept.my_permission) }}
            </el-tag>
          </div>
          <el-button circle @click="reloadAll">
            <el-icon><Refresh /></el-icon>
          </el-button>
        </div>
      </template>

      <el-alert
        v-if="!enabled"
        title="服务器未开启部门网盘功能"
        type="info"
        :closable="false"
        show-icon
      />

      <div v-else class="dept-layout" v-loading="treeLoading">
        <!-- 左：部门树 -->
        <div class="dept-aside">
          <el-tree
            v-if="deptTree.length"
            ref="treeRef"
            :data="deptTree"
            :props="{ label: 'name', children: 'children' }"
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
                    <el-tag size="small" :type="permTagType(data.my_permission)" effect="plain">
                      {{ permLabel(data.my_permission) }}
                    </el-tag>
                  </span>
            </template>
          </el-tree>
          <el-empty v-else description="暂无可访问的部门网盘" :image-size="70" />
        </div>

        <!-- 右：文件浏览 -->
        <div class="file-pane">
          <template v-if="selectedDeptId">
            <div class="toolbar">
              <div class="left">
                <el-button size="small" :disabled="folderPath.length === 0" @click="goUp">
                  <el-icon><Top /></el-icon>&nbsp;上级
                </el-button>
                <el-breadcrumb separator="/" class="crumb">
                  <el-breadcrumb-item @click="enterRoot">
                    <span class="crumb-link">{{ selectedDept?.name }}</span>
                  </el-breadcrumb-item>
                  <el-breadcrumb-item
                    v-for="(f, i) in folderPath"
                    :key="f.id"
                    @click="jumpTo(i)"
                  >
                    <span class="crumb-link">{{ f.file_name }}</span>
                  </el-breadcrumb-item>
                </el-breadcrumb>
              </div>
              <div class="right">
                <span class="quota">
                  空间：{{ formatSize(selectedDept?.used_storage) }} /
                  {{ selectedDept?.storage_quota ? formatSize(selectedDept.storage_quota) : '不限' }}
                </span>
                <el-button
                  v-if="writable"
                  size="small"
                  type="success"
                  plain
                  @click="createFolder"
                >
                  <el-icon><FolderAdd /></el-icon>&nbsp;新建文件夹
                </el-button>
                <el-button v-if="writable" size="small" type="primary" @click="pickAndUpload">
                  <el-icon><Upload /></el-icon>&nbsp;上传
                </el-button>
                <el-button
                  size="small"
                  :disabled="!selection.length"
                  @click="downloadRows(selection)"
                >
                  <el-icon><Download /></el-icon>&nbsp;下载
                </el-button>
              </div>
            </div>

            <el-alert
              v-if="!writable"
              title="当前目录仅有只读权限：可浏览、双击查看与下载，不可上传或修改"
              type="info"
              :closable="false"
              show-icon
              class="readonly-tip"
            />
            <el-alert
              v-else
              title="双击文件将在本机临时打开：保存后自动回传；也可直接拖入文件/文件夹上传"
              type="success"
              :closable="false"
              show-icon
              class="readonly-tip"
            />

            <el-table
              :data="items"
              v-loading="loading"
              border
              stripe
              size="small"
              height="420"
              @row-dblclick="openRow"
              @selection-change="(rows) => (selection = rows)"
            >
              <el-table-column type="selection" width="42" />
              <el-table-column label="名称" min-width="260">
                <template #default="{ row }">
                  <span class="name-cell" :class="{ link: row.is_folder }">
                    <FileIcon class="file-icon" :row="row" :size="18" />
                    <span>{{ row.file_name }}</span>
                    <el-tag
                      v-if="!row.is_folder && row.access === 'read_only'"
                      size="small"
                      type="info"
                      effect="plain"
                      class="row-perm"
                    >
                      只读
                    </el-tag>
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="大小" width="100">
                <template #default="{ row }">
                  {{ row.is_folder ? '-' : formatSize(row.file_size) }}
                </template>
              </el-table-column>
              <el-table-column label="类型" width="90">
                <template #default="{ row }">
                  {{ row.is_folder ? '文件夹' : row.file_suffix || '未知' }}
                </template>
              </el-table-column>
              <el-table-column label="上传时间" width="160">
                <template #default="{ row }">{{ formatTime(row.upload_time) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="230" fixed="right">
                <template #default="{ row }">
                  <el-button
                    v-if="!row.is_folder"
                    link
                    type="primary"
                    @click.stop="openRow(row)"
                  >
                    打开
                  </el-button>
                  <el-button link type="primary" @click.stop="downloadRows([row])">
                    下载
                  </el-button>
                  <template v-if="canWrite(row.access)">
                    <el-button link type="warning" @click.stop="renameRow(row)">重命名</el-button>
                    <el-button link type="primary" @click.stop="openMove(row)">移动</el-button>
                    <el-button link type="danger" @click.stop="removeRow(row)">删除</el-button>
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
          </template>

          <el-empty v-else description="请选择左侧部门" :image-size="100" />
        </div>
      </div>
    </el-card>

    <!-- 拖拽遮罩 -->
    <div v-if="dragActive" class="drop-mask">
      <div class="drop-tip" :class="{ denied: !writable }">
        <el-icon size="40"><Upload /></el-icon>
        <p>{{ writable ? '松开以上传到当前目录' : '当前目录无上传权限' }}</p>
      </div>
    </div>

    <!-- 移动弹窗 -->
    <dept-move-dialog
      v-model="moveVisible"
      :node="activeNode"
      :department-id="selectedDeptId"
      @moved="doMove"
    />

    <!-- 传输进度 -->
    <el-dialog v-model="transfer.visible" :title="transferTitle" width="440px" :close-on-click-modal="false" :show-close="false">
      <el-progress :percentage="transferPercent" :status="transfer.status" />
      <p class="transfer-name">{{ transfer.fileName || '准备中…' }}</p>
      <p v-if="transfer.phase === 'download'" class="transfer-sub">
        已完成 {{ transfer.current }} / {{ transfer.total }}
      </p>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import DeptMoveDialog from '../components/DeptMoveDialog.vue'
import FileIcon from '../components/FileIcon.vue'
import { canWrite, findDeptNode, firstReadableId, permLabel, permTagType } from '../../lib/dept/dept-tree.js'
import { collectDropEntries } from '../../lib/dept/drag-drop.js'
import { uploadGroupsToDept } from '../../lib/dept/upload-tree.js'

const router = useRouter()

async function unwrap(promise) {
  const res = await promise
  if (!res.success) throw new Error(res.error || '操作失败')
  return res.data
}

// IPC 仅接受可结构化克隆的纯对象；el-table 行是 Vue reactive Proxy，
// 直接传入会在 contextBridge 边界抛 "An object could not be cloned."
function toPlain(value) {
  if (value === null || typeof value !== 'object') return value
  return JSON.parse(JSON.stringify(value))
}

// ---- 基础状态 ----
const enabled = ref(true)
const treeLoading = ref(false)
const treeRef = ref()
const deptTree = ref([])
const selectedDeptId = ref(null)

const folderPath = ref([]) // 当前部门内的文件夹链
const items = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(50)
const loading = ref(false)
const selection = ref([])
const moveVisible = ref(false)
const activeNode = ref({})
const dragActive = ref(false)

const parentId = computed(() =>
  folderPath.value.length ? folderPath.value[folderPath.value.length - 1].id : null
)
const selectedDept = computed(() => findDeptNode(deptTree.value, selectedDeptId.value))
// 部门根目录取部门权限；文件夹内以最近一次列表返回的容器权限为准
const containerAccess = ref('none')
function isCurrentWritable() {
  if (folderPath.value.length === 0) return canWrite(selectedDept.value?.my_permission)
  return canWrite(containerAccess.value)
}
const writable = computed(() => isCurrentWritable())

const transfer = reactive({
  visible: false,
  phase: '',
  current: 0,
  total: 0,
  fileName: '',
  percent: 0,
  status: '',
  mode: '',
})
const transferTitle = computed(() => (transfer.phase === 'download' ? '下载到本地' : '上传到部门网盘'))
const transferPercent = computed(() => {
  if (transfer.phase === 'upload') return transfer.percent || 0
  if (transfer.total > 0) return Math.round((transfer.current / transfer.total) * 100)
  return 0
})

let listSeq = 0

// ---- 展示辅助 ----
function formatSize(n) {
  if (n == null) return '-'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = Number(n)
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}
function formatTime(t) {
  return t ? new Date(t).toLocaleString('zh-CN', { hour12: false }) : '—'
}

// ---- 数据加载 ----
async function loadTree(selectInitial = false) {
  treeLoading.value = true
  try {
    deptTree.value = (await unwrap(window.zhy.dept.tree())) || []
    if (selectInitial) {
      const initial = firstReadableId(deptTree.value)
      if (initial) {
        selectedDeptId.value = initial
        treeRef.value?.setCurrentKey(initial)
        await loadList()
      }
    }
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    treeLoading.value = false
  }
}

async function loadList() {
  if (!selectedDeptId.value) return
  const seq = ++listSeq
  loading.value = true
  selection.value = []
  try {
    const data = await unwrap(
      window.zhy.dept.list({
        departmentId: selectedDeptId.value,
        parentId: parentId.value,
        page: page.value,
        size: size.value,
      })
    )
    if (seq !== listSeq) return
    items.value = data.items || []
    total.value = data.total || 0
    containerAccess.value = data.access || selectedDept.value?.my_permission || 'none'
    // 同步当前文件夹链中最后一环的权限标注
    if (folderPath.value.length) {
      folderPath.value[folderPath.value.length - 1].access = containerAccess.value
    }
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

async function reloadAll() {
  page.value = 1
  await loadTree(false)
  await loadList()
}

function onDeptClick(data) {
  if (!data.my_permission || data.my_permission === 'none') {
    ElMessage.warning('无权访问该部门')
    return
  }
  selectedDeptId.value = data.id
  folderPath.value = []
  page.value = 1
  loadList()
}
function enterRoot() {
  folderPath.value = []
  page.value = 1
  loadList()
}
function enterFolder(row) {
  folderPath.value.push(row)
  page.value = 1
  loadList()
}
function goUp() {
  folderPath.value.pop()
  page.value = 1
  loadList()
}
function jumpTo(i) {
  folderPath.value = folderPath.value.slice(0, i + 1)
  page.value = 1
  loadList()
}
function onPageChange(p) {
  page.value = p
  loadList()
}
async function openRow(row) {
  if (row.is_folder) {
    enterFolder(row)
    return
  }
  try {
    const data = await unwrap(window.zhy.dept.openFile(toPlain(row)))
    if (data.access === 'read_write') {
      ElMessage.success(`已打开「${row.file_name}」，在外部程序保存后将自动回传并解除锁定`)
    } else if (data.lockedBy) {
      ElMessage.info(
        `「${row.file_name}」正被「${data.lockedBy}」编辑，已以只读方式打开；对方保存后即可编辑`
      )
    } else {
      ElMessage.info(`「${row.file_name}」以只读方式打开，修改请用「下载」另存，不会回传服务器`)
    }
  } catch (e) {
    ElMessage.error(e.message)
  }
}

// ---- 下载 ----
async function downloadRows(rows) {
  if (!rows.length) return
  const targetDir = await window.zhy.chooseFolder()
  if (!targetDir) return
  const nodes = rows.map((r) => ({
    id: r.id,
    file_name: r.file_name,
    is_folder: r.is_folder,
    department_id: selectedDeptId.value,
  }))
  Object.assign(transfer, {
    visible: true,
    phase: 'download',
    current: 0,
    total: 0,
    fileName: '',
    percent: 0,
    status: '',
  })
  try {
    const res = await unwrap(window.zhy.dept.download(nodes, targetDir))
    transfer.status = 'success'
    if (res.failed?.length) {
      ElMessage.warning(`下载完成 ${res.success} 个，失败 ${res.failed.length} 个：${res.failed.map((f) => f.name).join('、')}`)
    } else {
      ElMessage.success(`已下载 ${res.success} 个文件到「${targetDir}」`)
    }
  } catch (e) {
    transfer.status = 'exception'
    ElMessage.error(e.message)
  } finally {
    setTimeout(() => {
      transfer.visible = false
    }, 600)
  }
}

// ---- 上传（按钮 + 拖拽统一走结构化分组） ----
async function runUploadGroups(groups) {
  if (!groups.length) return
  const deptId = selectedDeptId.value
  const parent = parentId.value
  const api = {
    listFolders: async (pid) =>
      (await unwrap(window.zhy.dept.folders({ departmentId: deptId, parentId: pid }))).items || [],
    createFolder: async (pid, name) =>
      unwrap(window.zhy.dept.createFolder({ departmentId: deptId, parentId: pid, fileName: name })),
    plan: async (paths, pid) => unwrap(window.zhy.dept.planUploads(paths, deptId, pid)),
    upload: async (plans, pid, overwrite) =>
      unwrap(window.zhy.dept.upload(plans, deptId, pid, overwrite)),
    askOverwrite: async (n) => {
      try {
        await ElMessageBox.confirm(
          `检测到 ${n} 个同名文件内容不同，是否用本地文件覆盖？选择“跳过”将保留服务端版本。`,
          '同名冲突',
          { confirmButtonText: '覆盖', cancelButtonText: '跳过', type: 'warning' }
        )
        return true
      } catch {
        return false
      }
    },
  }
  Object.assign(transfer, {
    visible: true,
    phase: 'upload',
    current: 0,
    total: 0,
    fileName: '',
    percent: 0,
    status: '',
    mode: '',
  })
  try {
    const res = await uploadGroupsToDept(groups, {
      departmentId: deptId,
      parentId: parent,
      ...api,
    })
    transfer.status = 'success'
    const parts = [`成功 ${res.success} 个`]
    if (res.skipped) parts.push(`跳过 ${res.skipped} 个`)
    if (res.failed.length) parts.push(`失败 ${res.failed.length} 个`)
    ElMessage.success(`上传完成：${parts.join('，')}`)
    await loadList()
  } catch (e) {
    transfer.status = 'exception'
    ElMessage.error(e.message)
  } finally {
    setTimeout(() => {
      transfer.visible = false
    }, 600)
  }
}

async function pickAndUpload() {
  const paths = await unwrap(window.zhy.dept.chooseFiles())
  if (!paths.length) return
  await runUploadGroups([{ rootName: null, files: paths }])
}

// ---- 拖拽 ----
let dragDepth = 0
function onDragEnter(e) {
  e.preventDefault()
  dragDepth += 1
  dragActive.value = true
}
function onDragLeave() {
  dragDepth -= 1
  if (dragDepth <= 0) {
    dragDepth = 0
    dragActive.value = false
  }
}
async function onDrop(e) {
  e.preventDefault()
  dragDepth = 0
  dragActive.value = false
  if (!isCurrentWritable()) {
    ElMessage.error('当前目录无上传权限')
    return
  }
  try {
    const groups = await collectDropEntries(e.dataTransfer, {
      getPathForFile: (f) => window.zhy.getPathForFile(f),
      statPaths: async (paths) => unwrap(window.zhy.dept.statPaths(paths)),
      walkDir: async (d) => unwrap(window.zhy.dept.walkDir(d)),
    })
    if (!groups.length) {
      ElMessage.info('未发现可上传的文件')
      return
    }
    await runUploadGroups(groups)
  } catch (err) {
    ElMessage.error(err.message)
  }
}

// ---- 文件夹/重命名/移动/删除 ----
async function createFolder() {
  let name
  try {
    ({ value: name } = await ElMessageBox.prompt('请输入文件夹名称', '新建文件夹', {
      confirmButtonText: '创建',
      cancelButtonText: '取消',
      inputPattern: /^[^\\/:*?"<>|]+$/,
      inputErrorMessage: '名称不能为空或包含 \\ / : * ? " < > |',
    }))
  } catch {
    return
  }
  try {
    await unwrap(
      window.zhy.dept.createFolder({
        departmentId: selectedDeptId.value,
        parentId: parentId.value,
        fileName: name.trim(),
      })
    )
    ElMessage.success('已创建')
    await loadList()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function renameRow(row) {
  let name
  try {
    ({ value: name } = await ElMessageBox.prompt('请输入新名称', '重命名', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      inputValue: row.file_name,
      inputPattern: /^[^\\/:*?"<>|]+$/,
      inputErrorMessage: '名称不能为空或包含 \\ / : * ? " < > |',
    }))
  } catch {
    return
  }
  try {
    await unwrap(window.zhy.dept.rename(row.id, name.trim()))
    ElMessage.success('已重命名')
    await loadList()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function removeRow(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除「${row.file_name}」？${row.is_folder ? '文件夹内全部内容将一并删除。' : ''}`,
      '删除确认',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await unwrap(window.zhy.dept.remove(row.id))
    ElMessage.success('已删除')
    await loadList()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

function openMove(row) {
  activeNode.value = row
  moveVisible.value = true
}
async function doMove(targetParentId) {
  try {
    await unwrap(window.zhy.dept.move(activeNode.value.id, targetParentId))
    ElMessage.success('已移动')
    moveVisible.value = false
    await loadList()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

// ---- 事件订阅 ----
const unsubs = []
onMounted(async () => {
  unsubs.push(
    window.zhy.on('dept:progress', (p) => {
      if (!transfer.visible) return
      transfer.phase = p.phase || transfer.phase
      transfer.current = p.current ?? transfer.current
      transfer.total = p.total ?? transfer.total
      transfer.fileName = p.fileName || transfer.fileName
      if (typeof p.percent === 'number') transfer.percent = p.percent
    }),
    window.zhy.on('dept:toast', (t) => {
      if (t?.type === 'success') ElMessage.success(t.message)
      else if (t?.type === 'error') ElMessage.error(t.message)
      else ElMessage.info(t?.message)
    })
  )
  try {
    const flags = await unwrap(window.zhy.dept.featureFlags())
    enabled.value = Boolean(flags?.department_drive)
    if (enabled.value) await loadTree(true)
  } catch (e) {
    enabled.value = false
    ElMessage.error(e.message)
  }
})
onUnmounted(() => unsubs.forEach((u) => u && u()))
</script>

<style scoped>
.dept-container {
  padding: 16px;
  min-height: 100vh;
  box-sizing: border-box;
}
.dept-card {
  width: 100%;
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.title {
  font-size: 16px;
  font-weight: 600;
}
.dept-layout {
  display: flex;
  gap: 12px;
  min-height: 520px;
}
.dept-aside {
  width: 240px;
  flex-shrink: 0;
  border-right: 1px solid var(--el-border-color-lighter);
  padding-right: 8px;
  max-height: 560px;
  overflow: auto;
}
.dept-node {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
}
.dept-node-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-pane {
  flex: 1;
  min-width: 0;
}
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.toolbar .right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.crumb {
  font-size: 13px;
}
.crumb-link {
  cursor: pointer;
  color: var(--el-color-primary);
}
.quota {
  font-size: 12px;
  color: #909399;
}
.readonly-tip {
  margin-bottom: 8px;
}
.name-cell {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.name-cell.link {
  cursor: pointer;
}
.file-icon {
  font-size: 16px;
}
.row-perm {
  margin-left: 4px;
}
.pager {
  margin-top: 8px;
  justify-content: flex-end;
}
.drop-mask {
  position: fixed;
  inset: 0;
  background: rgba(64, 158, 255, 0.12);
  border: 3px dashed var(--el-color-primary);
  z-index: 3000;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}
.drop-tip {
  background: #fff;
  border-radius: 12px;
  padding: 32px 56px;
  text-align: center;
  color: var(--el-color-primary);
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.12);
}
.drop-tip.denied {
  color: var(--el-color-danger);
}
.transfer-name {
  margin: 12px 0 0;
  font-size: 13px;
  word-break: break-all;
}
.transfer-sub {
  font-size: 12px;
  color: #909399;
}
</style>
