<template>
  <div v-loading="loading">
    <div class="head">
      <span class="page-title">监控仪表盘</span>
      <div class="head-tools">
        <span class="updated">更新于 {{ updatedAt }}</span>
        <el-switch
          v-model="autoRefresh"
          inline-prompt
          active-text="30s 自动"
          inactive-text="手动"
          @change="onToggleAuto"
        />
        <el-button circle @click="load"><el-icon><Refresh /></el-icon></el-button>
      </div>
    </div>

    <!-- 核心指标卡片 -->
    <el-row :gutter="16" class="cards">
      <el-col :xs="12" :sm="8" :md="4">
        <el-card class="metric-card">
          <div class="metric-label">CPU 使用率</div>
          <div class="metric-value" :class="levelClass(m?.cpu?.percent)">
            {{ fmtPct(m?.cpu?.percent) }}
          </div>
          <div class="bar"><div class="bar-inner cpu" :style="barStyle(m?.cpu?.percent)" /></div>
          <div class="metric-sub">
            {{ m?.cpu?.limited ? `限额 ${m.cpu.quota_cores} / ${m.cpu.cores} 核` : `${m?.cpu?.cores ?? '-'} 核` }}
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="8" :md="4">
        <el-card class="metric-card">
          <div class="metric-label">内存</div>
          <div class="metric-value" :class="levelClass(m?.memory?.percent)">
            {{ fmtPct(m?.memory?.percent) }}
          </div>
          <div class="bar"><div class="bar-inner mem" :style="barStyle(m?.memory?.percent)" /></div>
          <div class="metric-sub">
            {{ formatSize(m?.memory?.used) }} / {{ formatSize(m?.memory?.total) }}
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="8" :md="4">
        <el-card class="metric-card">
          <div class="metric-label">磁盘</div>
          <div class="metric-value" :class="levelClass(m?.disk?.percent)">
            {{ fmtPct(m?.disk?.percent) }}
          </div>
          <div class="bar"><div class="bar-inner disk" :style="barStyle(m?.disk?.percent)" /></div>
          <div class="metric-sub">
            {{ formatSize(m?.disk?.used) }} / {{ formatSize(m?.disk?.total) }}
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="8" :md="4">
        <el-card class="metric-card">
          <div class="metric-label">5 分钟在线</div>
          <div class="metric-value">{{ m?.online_users ?? '-' }}</div>
          <div class="metric-sub">最近 5 分钟活跃用户</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="8" :md="4">
        <el-card class="metric-card">
          <div class="metric-label">今日上行</div>
          <div class="metric-value">{{ formatSize(m?.traffic?.today_up) }}</div>
          <div class="metric-sub">上传流量</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="8" :md="4">
        <el-card class="metric-card">
          <div class="metric-label">今日下行</div>
          <div class="metric-value">{{ formatSize(m?.traffic?.today_down) }}</div>
          <div class="metric-sub">下载流量</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16">
      <!-- 近 7 天流量 -->
      <el-col :xs="24" :md="14">
        <el-card class="block">
          <template #header><span class="block-title">近 7 天流量</span></template>
          <TrafficChart :days="m?.traffic?.days || []" />
        </el-card>
      </el-col>

      <!-- 存储统计 -->
      <el-col :xs="24" :md="10">
        <el-card class="block">
          <template #header><span class="block-title">存储统计</span></template>
          <div class="storage-line">
            <span>已用空间</span>
            <span>{{ formatSize(m?.storage?.used) }}</span>
          </div>
          <div class="bar big">
            <div class="bar-inner disk" :style="quotaBarStyle" />
          </div>
          <div class="storage-line sub">
            <span>配额总量</span>
            <span>{{ formatSize(m?.storage?.quota_total) }}</span>
          </div>
          <el-divider />
          <el-row :gutter="8">
            <el-col :span="12">
              <div class="storage-line"><span>个人盘</span><span>{{ formatSize(m?.storage?.personal_used) }}</span></div>
            </el-col>
            <el-col :span="12">
              <div class="storage-line"><span>部门盘</span><span>{{ formatSize(m?.storage?.department_used) }}</span></div>
            </el-col>
            <el-col :span="12">
              <div class="storage-line"><span>文件数</span><span>{{ m?.storage?.file_count ?? '-' }}</span></div>
            </el-col>
            <el-col :span="12">
              <div class="storage-line"><span>文件夹数</span><span>{{ m?.storage?.folder_count ?? '-' }}</span></div>
            </el-col>
            <el-col :span="12">
              <div class="storage-line"><span>用户数</span><span>{{ m?.storage?.user_count ?? '-' }}</span></div>
            </el-col>
            <el-col :span="12">
              <div class="storage-line"><span>部门数</span><span>{{ m?.storage?.department_count ?? '-' }}</span></div>
            </el-col>
          </el-row>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, h } from 'vue'
import { ElMessage } from 'element-plus'
import { getMetrics } from '../../api/admin'
import { formatSize } from '../../utils/format'

const m = ref(null)
const loading = ref(false)
const autoRefresh = ref(true)
const updatedAt = ref('-')
let timer = null

const quotaBarStyle = computed(() => {
  const used = m.value?.storage?.used || 0
  const total = m.value?.storage?.quota_total || 0
  const pct = total > 0 ? Math.min((used / total) * 100, 100) : 0
  return { width: `${pct.toFixed(1)}%` }
})

function fmtPct(v) {
  return v === undefined || v === null ? '-' : `${Number(v).toFixed(1)}%`
}

function barStyle(v) {
  return { width: `${Math.max(0, Math.min(Number(v) || 0, 100))}%` }
}

function levelClass(v) {
  if (v >= 90) return 'level-danger'
  if (v >= 70) return 'level-warn'
  return 'level-ok'
}

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const res = await getMetrics()
    m.value = res.data
    updatedAt.value = new Date().toLocaleTimeString()
  } finally {
    if (!silent) loading.value = false
  }
}

function onToggleAuto(val) {
  if (val) {
    startTimer()
    ElMessage.success('已开启 30 秒自动刷新')
  } else {
    stopTimer()
  }
}

function startTimer() {
  stopTimer()
  timer = setInterval(() => load(true), 30000)
}

function stopTimer() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

onMounted(async () => {
  await load()
  if (autoRefresh.value) startTimer()
})

onBeforeUnmount(stopTimer)

// 近 7 天流量柱状图（纯 SVG，不引入图表库）
const TrafficChart = {
  props: { days: { type: Array, default: () => [] } },
  setup(props) {
    const W = 560
    const H = 220
    const PAD_L = 46
    const PAD_R = 12
    const PAD_T = 16
    const PAD_B = 34

    return () => {
      const days = props.days
      const maxVal = Math.max(1, ...days.map((d) => Math.max(d.up, d.down)))
      const innerW = W - PAD_L - PAD_R
      const innerH = H - PAD_T - PAD_B
      const groupW = days.length ? innerW / days.length : innerW
      const barW = Math.min(16, groupW / 3)

      const y = (v) => PAD_T + innerH - (v / maxVal) * innerH
      const ticks = [0, 0.25, 0.5, 0.75, 1].map((r) => {
        const val = maxVal * r
        const yy = y(val)
        return h('g', [
          h('line', {
            x1: PAD_L, x2: W - PAD_R, y1: yy, y2: yy,
            stroke: '#eef2f7', 'stroke-width': 1,
          }),
          h('text', { x: 6, y: yy + 4, 'font-size': 10, fill: '#94a3b8' }, compactSize(val)),
        ])
      })

      const bars = []
      const labels = []
      days.forEach((d, i) => {
        const cx = PAD_L + groupW * i + groupW / 2
        const upX = cx - barW - 1
        const downX = cx + 1
        bars.push(
          h('rect', {
            x: upX, y: y(d.up), width: barW,
            height: Math.max(0, PAD_T + innerH - y(d.up)),
            fill: '#22c55e', rx: 2,
          }),
          h('rect', {
            x: downX, y: y(d.down), width: barW,
            height: Math.max(0, PAD_T + innerH - y(d.down)),
            fill: '#3b82f6', rx: 2,
          }),
        )
        labels.push(
          h('text', {
            x: cx, y: H - 12, 'text-anchor': 'middle',
            'font-size': 10, fill: '#64748b',
          }, d.date.slice(5)),
        )
      })

      // 柱上 tooltip（rect > title 嵌套）
      const tipBars = []
      days.forEach((d, i) => {
        const cx = PAD_L + groupW * i + groupW / 2
        const upX = cx - barW - 1
        const downX = cx + 1
        tipBars.push(
          h('rect', {
            x: upX, y: y(d.up), width: barW,
            height: Math.max(0, PAD_T + innerH - y(d.up)),
            fill: 'transparent',
          }, [h('title', {}, `${d.date} 上行 ${formatSize(d.up)}`)]),
          h('rect', {
            x: downX, y: y(d.down), width: barW,
            height: Math.max(0, PAD_T + innerH - y(d.down)),
            fill: 'transparent',
          }, [h('title', {}, `${d.date} 下行 ${formatSize(d.down)}`)]),
        )
      })

      return h('div', [
        h('svg', { viewBox: `0 0 ${W} ${H}`, width: '100%' }, [
          ...ticks,
          h('g', bars),
          h('g', { style: 'pointer-events: all' }, tipBars),
          ...labels,
        ]),
        h('div', { class: 'legend' }, [
          h('span', { class: 'legend-item' }, [
            h('i', { class: 'dot up' }), '上行',
          ]),
          h('span', { class: 'legend-item' }, [
            h('i', { class: 'dot down' }), '下行',
          ]),
        ]),
      ])
    }
  },
}

function compactSize(v) {
  if (v >= 1024 ** 3) return `${(v / 1024 ** 3).toFixed(1)}G`
  if (v >= 1024 ** 2) return `${(v / 1024 ** 2).toFixed(0)}M`
  if (v >= 1024) return `${(v / 1024).toFixed(0)}K`
  return `${v}`
}
</script>

<style scoped>
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.page-title {
  font-size: 17px;
  font-weight: 600;
  color: #1e293b;
}

.head-tools {
  display: flex;
  align-items: center;
  gap: 12px;
}

.updated {
  font-size: 12px;
  color: #94a3b8;
}

.cards {
  margin-bottom: 4px;
}

.metric-card {
  margin-bottom: 16px;
}

.metric-label {
  font-size: 13px;
  color: #64748b;
}

.metric-value {
  font-size: 26px;
  font-weight: 700;
  color: #1e293b;
  margin: 4px 0 8px;
}

.level-ok {
  color: #16a34a;
}

.level-warn {
  color: #d97706;
}

.level-danger {
  color: #dc2626;
}

.metric-sub {
  margin-top: 8px;
  font-size: 12px;
  color: #94a3b8;
}

.bar {
  height: 6px;
  background: #eef2f7;
  border-radius: 3px;
  overflow: hidden;
}

.bar.big {
  height: 10px;
  margin: 8px 0;
}

.bar-inner {
  height: 100%;
  border-radius: 3px;
  transition: width 0.4s ease;
}

.bar-inner.cpu {
  background: linear-gradient(90deg, #60a5fa, #2563eb);
}

.bar-inner.mem {
  background: linear-gradient(90deg, #34d399, #059669);
}

.bar-inner.disk {
  background: linear-gradient(90deg, #fbbf24, #ea580c);
}

.block {
  margin-bottom: 16px;
  min-height: 260px;
}

.block-title {
  font-weight: 600;
  color: #1e293b;
}

.storage-line {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: #334155;
  margin: 4px 0;
}

.storage-line.sub {
  color: #94a3b8;
  font-size: 12px;
}

:deep(.legend) {
  display: flex;
  gap: 16px;
  justify-content: center;
  margin-top: 4px;
  font-size: 12px;
  color: #64748b;
}

:deep(.dot) {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
  margin-right: 4px;
}

:deep(.dot.up) {
  background: #22c55e;
}

:deep(.dot.down) {
  background: #3b82f6;
}
</style>
