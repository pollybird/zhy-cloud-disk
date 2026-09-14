<template>
  <el-card>
    <div class="toolbar">
      <div class="left">
        <span class="title">插件管理</span>
        <span class="hint">插件与主进程同进程运行，仅管理员可安装/启用</span>
      </div>
      <div class="right">
        <el-button :loading="scanning" @click="rescan">
          <el-icon><Refresh /></el-icon>&nbsp;重新扫描
        </el-button>
      </div>
    </div>

    <!-- 扫描异常提示 -->
    <el-alert
      v-for="(err, i) in scanErrors"
      :key="i"
      :title="`插件扫描异常：${err}`"
      type="warning"
      show-icon
      :closable="false"
      class="scan-error"
    />

    <el-table :data="items" v-loading="loading" border stripe>
      <el-table-column prop="name" label="名称" min-width="150">
        <template #default="{ row }">
          <span class="mono">{{ row.name }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="version" label="版本" width="90" />
      <el-table-column prop="author" label="作者" width="130" show-overflow-tooltip />
      <el-table-column prop="description" label="描述" min-width="220" show-overflow-tooltip />
      <el-table-column label="支持后缀" min-width="180">
        <template #default="{ row }">
          <el-tag
            v-for="ext in row.supported_exts.slice(0, 6)"
            :key="ext"
            size="small"
            class="ext-tag"
          >
            {{ ext }}
          </el-tag>
          <el-tooltip
            v-if="row.supported_exts.length > 6"
            :content="row.supported_exts.slice(6).join(', ')"
            placement="top"
          >
            <el-tag size="small" type="info">+{{ row.supported_exts.length - 6 }}</el-tag>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="来源" width="90">
        <template #default="{ row }">
          <el-tag :type="row.source === 'builtin' ? 'primary' : 'success'" size="small" effect="plain">
            {{ row.source === 'builtin' ? '内置' : '外部' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="启用" width="90">
        <template #default="{ row }">
          <el-switch
            :model-value="row.enabled"
            :loading="row._switching"
            @change="(v) => onToggle(row, v)"
          />
        </template>
      </el-table-column>
      <el-table-column label="状态" min-width="150">
        <template #default="{ row }">
          <el-tag v-if="row.last_error" type="danger" size="small" effect="plain">
            {{ row.last_error }}
          </el-tag>
          <el-tag v-else-if="row.enabled" type="success" size="small" effect="plain">运行中</el-tag>
          <el-tag v-else type="info" size="small" effect="plain">已禁用</el-tag>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listPlugins, registerPlugins, setPluginEnabled } from '../../api/plugin'

const items = ref([])
const scanErrors = ref([])
const loading = ref(false)
const scanning = ref(false)

async function load() {
  loading.value = true
  try {
    const res = await listPlugins()
    items.value = res.data.items
    scanErrors.value = res.data.scan_errors || []
  } finally {
    loading.value = false
  }
}

async function rescan() {
  scanning.value = true
  try {
    const res = await registerPlugins()
    items.value = res.data.items
    scanErrors.value = res.data.scan_errors || []
    ElMessage.success('扫描完成')
  } finally {
    scanning.value = false
  }
}

async function onToggle(row, enabled) {
  row._switching = true
  try {
    await setPluginEnabled(row.name, enabled)
    row.enabled = enabled
    ElMessage.success(enabled ? `插件 ${row.name} 已启用` : `插件 ${row.name} 已禁用`)
  } catch (e) {
    ElMessage.error(e?.msg || '操作失败')
  } finally {
    row._switching = false
  }
}

onMounted(load)
</script>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.left {
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.title {
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
}

.hint {
  font-size: 12px;
  color: #94a3b8;
}

.scan-error {
  margin-bottom: 12px;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.ext-tag {
  margin-right: 4px;
}
</style>
