// 文件后缀分类与图标映射（个人空间 / 部门网盘共用）

// 细分类别：每个类别对应一种色带颜色
const CATEGORY_TABLE = {
  // PDF
  pdf: 'pdf',
  // Word / 文档
  doc: 'word', docx: 'word', docm: 'word', dot: 'word', dotx: 'word',
  rtf: 'word', odt: 'word', wps: 'word',
  // Excel / 表格
  xls: 'sheet', xlsx: 'sheet', xlsm: 'sheet', xlsb: 'sheet', csv: 'sheet',
  ods: 'sheet', numbers: 'sheet',
  // PPT / 演示
  ppt: 'slide', pptx: 'slide', pps: 'slide', ppsx: 'slide', key: 'slide', odp: 'slide',
  // 纯文本 / 配置
  txt: 'text', log: 'text', ini: 'text', conf: 'text', cfg: 'text',
  properties: 'text',
  // Markdown
  md: 'markdown', markdown: 'markdown',
  // 图片
  jpg: 'image', jpeg: 'image', png: 'image', gif: 'image', webp: 'image',
  bmp: 'image', svg: 'image', ico: 'image', tif: 'image', tiff: 'image',
  heic: 'image', heif: 'image', raw: 'image', psd: 'image', ai: 'image',
  // 视频
  mp4: 'video', flv: 'video', mov: 'video', avi: 'video', mkv: 'video',
  webm: 'video', wmv: 'video', m4v: 'video', mpg: 'video', mpeg: 'video',
  rmvb: 'video', '3gp': 'video', ts: 'video',
  // 音频
  mp3: 'audio', wav: 'audio', flac: 'audio', aac: 'audio', ogg: 'audio',
  m4a: 'audio', wma: 'audio', ape: 'audio',
  // 压缩包
  zip: 'archive', rar: 'archive', '7z': 'archive', tar: 'archive',
  gz: 'archive', bz2: 'archive', xz: 'archive', jar: 'archive',
  // 代码
  js: 'code', mjs: 'code', cjs: 'code', ts: 'code', jsx: 'code', tsx: 'code',
  vue: 'code', py: 'code', java: 'code', c: 'code', h: 'code',
  cpp: 'code', cc: 'code', cxx: 'code', hpp: 'code', hxx: 'code',
  go: 'code', rs: 'code', rb: 'code', php: 'code', sh: 'code', bash: 'code',
  html: 'code', htm: 'code', css: 'code', scss: 'code', less: 'code',
  json: 'code', json5: 'code', xml: 'code', yml: 'code', yaml: 'code',
  toml: 'code', sql: 'code', lua: 'code', swift: 'code', kt: 'code',
  // 可执行 / 安装包
  exe: 'app', msi: 'app', apk: 'app', dmg: 'app', pkg: 'app',
  deb: 'app', rpm: 'app', app: 'app', bat: 'app', cmd: 'app',
}

// 类别 → 色带颜色（FileIcon 组件使用）
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

// 粗分类 → Element Plus 图标名（兼容旧调用方）
const CATEGORY_ICONS = {
  pdf: 'Document',
  word: 'Document',
  sheet: 'Document',
  slide: 'Document',
  text: 'Document',
  markdown: 'Document',
  image: 'Picture',
  video: 'VideoPlay',
  audio: 'Headset',
  archive: 'Files',
  code: 'Document',
  app: 'Document',
  other: 'Document',
}

// 旧粗分类颜色（iconColor 兼容）
const LEGACY_COLORS = {
  image: '#10b981',
  video: '#ef4444',
  document: '#3b82f6',
  audio: '#8b5cf6',
  archive: '#64748b',
}
const LEGACY_OF = {
  pdf: 'document', word: 'document', sheet: 'document', slide: 'document',
  text: 'document', markdown: 'document', image: 'image', video: 'video',
  audio: 'audio', archive: 'archive', code: 'document', app: 'document',
}

export function categoryOf(suffix) {
  return CATEGORY_TABLE[(suffix || '').toLowerCase()] || 'other'
}

/**
 * 文件图标的视觉描述：{ folder, color, label }
 * @param {{is_folder?:boolean, file_name?:string, file_suffix?:string}} row
 */
export function fileVisual(row = {}) {
  if (row.is_folder) return { folder: true, color: '#f59e0b', label: '' }
  let ext = (row.file_suffix || '').toLowerCase()
  if (!ext && row.file_name) {
    const m = /\.([^./\\]+)$/.exec(row.file_name)
    ext = m ? m[1].toLowerCase() : ''
  }
  const category = categoryOf(ext)
  return {
    folder: false,
    color: CATEGORY_COLORS[category] || CATEGORY_COLORS.other,
    label: (ext || '').slice(0, 4).toUpperCase(),
  }
}

// ---- 兼容旧 API（ShareAccessView 等仍在使用） ----
export function iconName(row) {
  if (row.is_folder) return 'Folder'
  return CATEGORY_ICONS[categoryOf(row.file_suffix)] || 'Document'
}

export function iconColor(row) {
  if (row.is_folder) return '#f59e0b'
  const cat = categoryOf(row.file_suffix)
  return LEGACY_COLORS[LEGACY_OF[cat]] || LEGACY_COLORS.document
}
