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
    <g clip-path="url(#clipId)">
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
import { fileVisual } from '../utils/fileCategory'

let seq = 0

const props = defineProps({
  // 文件节点：{ is_folder, file_name, file_suffix }
  row: { type: Object, default: () => ({}) },
  // 也可单独传参
  name: { type: String, default: '' },
  suffix: { type: String, default: '' },
  isFolder: { type: Boolean, default: false },
  size: { type: Number, default: 20 },
})

const clipId = `fti-clip-${++seq}`

const visual = computed(() =>
  fileVisual({
    is_folder: props.isFolder || props.row.is_folder,
    file_name: props.name || props.row.file_name,
    file_suffix: props.suffix || props.row.file_suffix,
  })
)
</script>

<style scoped>
.file-type-icon {
  flex: none;
  vertical-align: middle;
}
</style>
