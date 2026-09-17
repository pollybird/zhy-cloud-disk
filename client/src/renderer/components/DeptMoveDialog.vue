<template>
  <el-dialog
    :model-value="modelValue"
    title="移动到"
    width="420px"
    append-to-body
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <div v-loading="loading" class="move-tree-wrap">
      <el-tree
        ref="treeRef"
        :data="treeData"
        :props="{ label: 'label', children: 'children' }"
        node-key="id"
        highlight-current
        default-expand-all
        :expand-on-click-node="false"
        @node-click="onNodeClick"
      >
        <template #default="{ data }">
          <span :class="{ 'is-root': data.id === ROOT_KEY }">{{ data.label }}</span>
        </template>
      </el-tree>
    </div>
    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :disabled="targetId === undefined" @click="confirm">
        移动到此处
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  node: { type: Object, default: () => ({}) },
  departmentId: { type: Number, default: null },
})
const emit = defineEmits(['update:modelValue', 'moved'])

const ROOT_KEY = '__dept_root__'
const treeRef = ref()
const treeData = ref([])
const loading = ref(false)
const targetId = ref(undefined)

async function unwrap(promise) {
  const res = await promise
  if (!res.success) throw new Error(res.error || '操作失败')
  return res.data
}

async function buildTree(parentId) {
  const data = await unwrap(
    window.zhy.dept.folders({ departmentId: props.departmentId, parentId })
  )
  const out = []
  for (const f of data.items || []) {
    // 自身及其子树不可作为目标（跳过自身即不会继续向下展开）
    if (props.node && f.id === props.node.id) continue
    // eslint-disable-next-line no-await-in-loop
    const children = await buildTree(f.id)
    out.push({ id: f.id, label: f.file_name, children })
  }
  return out
}

watch(
  () => props.modelValue,
  async (visible) => {
    if (!visible) return
    targetId.value = undefined
    loading.value = true
    try {
      const children = await buildTree(null)
      treeData.value = [{ id: ROOT_KEY, label: '部门根目录', children }]
      // 默认高亮当前所在位置
      const currentId = props.node?.parent_id ?? ROOT_KEY
      treeRef.value?.setCurrentKey(currentId)
      targetId.value = currentId === ROOT_KEY ? null : currentId
    } catch (e) {
      ElMessage.error(e.message)
    } finally {
      loading.value = false
    }
  }
)

function onNodeClick(data) {
  targetId.value = data.id === ROOT_KEY ? null : data.id
}

async function confirm() {
  emit('moved', targetId.value)
}
</script>

<style scoped>
.move-tree-wrap {
  max-height: 360px;
  overflow: auto;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 8px;
}
.is-root {
  font-weight: 600;
}
</style>
