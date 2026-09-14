<template>
  <el-card>
    <div class="toolbar">
      <span class="title">我的分享</span>
      <div class="actions">
        <el-input
          v-model="keyword"
          placeholder="按文件名搜索"
          clearable
          style="width: 220px"
          @keyup.enter="onSearch"
          @clear="onSearch"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-button circle @click="loadList">
          <el-icon><Refresh /></el-icon>
        </el-button>
      </div>
    </div>

    <el-table :data="items" v-loading="loading" border stripe>
      <el-table-column label="文件名" min-width="220">
        <template #default="{ row }">
          <el-icon class="file-ico"><Document /></el-icon>
          <span>{{ row.file_name || '（文件已删除）' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="大小" width="100">
        <template #default="{ row }">
          {{ row.is_folder ? '-' : formatSize(row.file_size) }}
        </template>
      </el-table-column>
      <el-table-column label="访问方式" width="90">
        <template #default="{ row }">
          <el-tag :type="row.has_password ? 'warning' : 'success'" size="small">
            {{ row.has_password ? '加密' : '公开' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="statusType(row)" size="small">{{ statusText(row) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="view_count" label="浏览" width="80" />
      <el-table-column label="创建时间" width="170">
        <template #default="{ row }">{{ formatDateTime(row.create_time) }}</template>
      </el-table-column>
      <el-table-column label="到期时间" width="170">
        <template #default="{ row }">
          {{ row.expire_time ? formatDateTime(row.expire_time) : '永久有效' }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="210" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" :disabled="!row.effective" @click="copyLink(row)">
            复制链接
          </el-button>
          <el-button link type="primary" :disabled="!row.effective" @click="openLink(row)">
            打开
          </el-button>
          <el-button
            link
            type="danger"
            :disabled="row.status !== 'active' || !row.effective"
            @click="cancel(row)"
          >
            取消分享
          </el-button>
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

    <el-empty v-if="!loading && items.length === 0" description="还没有分享记录，去文件列表点“分享”创建吧" />
  </el-card>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { cancelShare, listShares, sharePageUrl } from '../../api/share'
import { formatDateTime, formatSize } from '../../utils/format'

const items = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const keyword = ref('')
const loading = ref(false)

async function loadList() {
  loading.value = true
  try {
    const params = { page: page.value, size: size.value }
    if (keyword.value.trim()) params.keyword = keyword.value.trim()
    const res = await listShares(params)
    items.value = res.data.items
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}

function onSearch() {
  page.value = 1
  loadList()
}

function onPageChange(p) {
  page.value = p
  loadList()
}

function statusType(row) {
  if (row.status === 'cancelled') return 'info'
  if (row.status === 'expired' || !row.effective) return 'danger'
  return 'success'
}

function statusText(row) {
  if (row.status === 'cancelled') return '已取消'
  if (row.status === 'expired' || !row.effective) return '已过期'
  return '有效'
}

async function copyLink(row) {
  try {
    await navigator.clipboard.writeText(sharePageUrl(row.share_code))
  } catch (e) {
    const ta = document.createElement('textarea')
    ta.value = sharePageUrl(row.share_code)
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    ta.remove()
  }
  ElMessage.success('分享链接已复制')
}

function openLink(row) {
  window.open(sharePageUrl(row.share_code), '_blank')
}

async function cancel(row) {
  await ElMessageBox.confirm(
    `取消后分享链接「${row.share_code}」将立即失效，确定取消？`,
    '取消分享',
    { type: 'warning', confirmButtonText: '取消分享', cancelButtonText: '再想想' },
  )
  await cancelShare(row.id)
  ElMessage.success('分享已取消')
  loadList()
}

onMounted(loadList)
</script>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.title {
  font-size: 16px;
  font-weight: 600;
  color: #1e293b;
}

.actions {
  display: flex;
  gap: 10px;
}

.file-ico {
  color: #3b82f6;
  margin-right: 6px;
  vertical-align: -2px;
}

.pager {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
