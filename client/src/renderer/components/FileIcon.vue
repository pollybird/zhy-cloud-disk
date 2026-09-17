<template>
  <!-- 文件夹：经典黄色文件夹 -->
  <svg
    v-if="visual.folder"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    class="file-type-icon"
    aria-label="文件夹"
  >
    <path
      d="M3.5 7.5A1.5 1.5 0 0 1 5 6h4.2l1.8 2.3h8A1.5 1.5 0 0 1 20.5 9.8v7.7a1.5 1.5 0 0 1-1.5 1.5H5a1.5 1.5 0 0 1-1.5-1.5Z"
      fill="#f7b500"
    />
    <path
      d="M3.5 9.5h17v8a1.5 1.5 0 0 1-1.5 1.5H5a1.5 1.5 0 0 1-1.5-1.5Z"
      fill="#f59e0b"
    />
  </svg>

  <!-- 文件：折角文档 + 底部类型色带 + 扩展名标签 -->
  <svg
    v-else
    :width="size"
    :height="size * (28 / 24)"
    viewBox="0 0 24 28"
    class="file-type-icon"
    :aria-label="visual.label || '文件'"
  >
    <defs>
      <clipPath :id="clipId">
        <rect x="1" y="1" width="22" height="26" rx="3" />
      </clipPath>
    </defs>
    <g :clip-path="`url(#${clipId})`">
      <rect x="1" y="1" width="22" height="26" rx="3" fill="#ffffff" />
      <rect x="1" y="17.5" width="22" height="9.5" :fill="visual.color" />
    </g>
    <!-- 折角 -->
    <path d="M14 1.5v5a1.5 1.5 0 0 0 1.5 1.5h5.5" fill="none" stroke="#cbd5e1" stroke-width="1.2" />
    <path d="M14 1.5 21 8h-5.5A1.5 1.5 0 0 1 14 6.5Z" fill="#f1f5f9" stroke="#cbd5e1" stroke-width="1" />
    <!-- 描边 -->
    <rect
      x="1"
      y="1"
      width="22"
      height="26"
      rx="3"
      fill="none"
      stroke="#cbd5e1"
      stroke-width="1.2"
    />
    <text
      x="12"
      y="24.6"
      text-anchor="middle"
      font-size="6.2"
      font-weight="700"
      font-family="Arial, 'Helvetica Neue', sans-serif"
      fill="#ffffff"
      letter-spacing="0.3"
    >{{ visual.label || 'FILE' }}</text>
  </svg>
</template>

<script setup>
import { computed } from 'vue'

// 后缀 → 细分类（与 web 端 frontend/src/utils/fileCategory.js 保持一致）
const CATEGORY_TABLE = {
  pdf: 'pdf',
  doc: 'word', docx: 'word', docm: 'word', dot: 'word', dotx: 'word',
  rtf: 'word', odt: 'word', wps: 'word',
  xls: 'sheet', xlsx: 'sheet', xlsm: 'sheet', xlsb: 'sheet', csv: 'sheet',
  ods: 'sheet', numbers: 'sheet',
  ppt: 'slide', pptx: 'slide', pps: 'slide', ppsx: 'slide', key: 'slide', odp: 'slide',
  txt: 'text', log: 'text', ini: 'text', conf: 'text', cfg: 'text', properties: 'text',
  md: 'markdown', markdown: 'markdown',
  jpg: 'image', jpeg: 'image', png: 'image', gif: 'image', webp: 'image',
  bmp: 'image', svg: 'image', ico: 'image', tif: 'image', tiff: 'image',
  heic: 'image', heif: 'image', raw: 'image', psd: 'image', ai: 'image',
  mp4: 'video', flv: 'video', mov: 'video', avi: 'video', mkv: 'video',
  webm: 'video', wmv: 'video', m4v: 'video', mpg: 'video', mpeg: 'video',
  rmvb: 'video', '3gp': 'video', ts: 'video',
  mp3: 'audio', wav: 'audio', flac: 'audio', aac: 'audio', ogg: 'audio',
  m4a: 'audio', wma: 'audio', ape: 'audio',
  zip: 'archive', rar: 'archive', '7z': 'archive', tar: 'archive',
  gz: 'archive', bz2: 'archive', xz: 'archive', jar: 'archive',
  js: 'code', mjs: 'code', cjs: 'code', ts: 'code', jsx: 'code', tsx: 'code',
  vue: 'code', py: 'code', java: 'code', c: 'code', h: 'code',
  cpp: 'code', cc: 'code', cxx: 'code', hpp: 'code', hxx: 'code',
  go: 'code', rs: 'code', rb: 'code', php: 'code', sh: 'code', bash: 'code',
  html: 'code', htm: 'code', css: 'code', scss: 'code', less: 'code',
  json: 'code', json5: 'code', xml: 'code', yml: 'code', yaml: 'code',
  toml: 'code', sql: 'code', lua: 'code', swift: 'code', kt: 'code',
  exe: 'app', msi: 'app', apk: 'app', dmg: 'app', pkg: 'app',
  deb: 'app', rpm: 'app', app: 'app', bat: 'app', cmd: 'app',
}

const CATEGORY_COLORS = {
  pdf: '#d93025',
  word: '#2b7cd3',
  sheet: '#21a366',
  slide: '#ea580c',
  text: '#64748b',
  markdown: '#4f46e5',
  image: '#0891b2',
  video: '#9333ea',
  audio: '#d97706',
  archive: '#b45309',
  code: '#db2777',
  app: '#334155',
  other: '#94a3b8',
}

function fileVisual({ isFolder, name, suffix } = {}) {
  if (isFolder) return { folder: true, color: '#f59e0b', label: '' }
  let ext = (suffix || '').toLowerCase()
  if (!ext && name) {
    const m = /\.([^./\\]+)$/.exec(name)
    ext = m ? m[1].toLowerCase() : ''
  }
  return {
    folder: false,
    color: CATEGORY_COLORS[CATEGORY_TABLE[ext]] || CATEGORY_COLORS.other,
    label: (ext || '').slice(0, 4).toUpperCase(),
  }
}

let seq = 0

const props = defineProps({
  row: { type: Object, default: () => ({}) },
  name: { type: String, default: '' },
  suffix: { type: String, default: '' },
  isFolder: { type: Boolean, default: false },
  size: { type: Number, default: 18 },
})

const clipId = `fti-clip-${++seq}`

const visual = computed(() =>
  fileVisual({
    isFolder: props.isFolder || props.row.is_folder,
    name: props.name || props.row.file_name,
    suffix: props.suffix || props.row.file_suffix,
  })
)
</script>

<style scoped>
.file-type-icon {
  flex: none;
  vertical-align: middle;
}
</style>
