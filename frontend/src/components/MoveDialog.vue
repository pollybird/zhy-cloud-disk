<template>
  <el-dialog
    :model-value="modelValue"
    title="移动到"
    width="440px"
    @update:model-value="$emit('update:modelValue', $event)"
    @open="handleOpen"
  >
    <el-tree
      ref="treeRef"
      :props="treeProps"
      :load="loadNode"
      lazy
      node-key="id"
      highlight-current
      :expand-on-click-node="false"
      :default-expanded-keys="[0]"
      @current-change="onCurrentChange"
    />
    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="saving" @click="confirm">
        移动到此处
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listChildFolders, moveFile } from '../api/file'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  node: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['update:modelValue', 'moved'])

const treeRef = ref()
const treeProps = { label: 'label', children: 'children', isLeaf: 'leaf', disabled: 'disabled' }
const targetId = ref(null)
const saving = ref(false)

function handleOpen() {
  targetId.value = null
}

function isUnderMovedNode(treeNode) {
  // 判断当前展开节点是否位于被移动文件夹的子树内
  let cur = treeNode
  while (cur && cur.data) {
    if (cur.data.id === props.node.id) return true
    cur = cur.parent
  }
  return false
}

async function loadNode(node, resolve) {
  try {
    if (node.level === 0) {
      resolve([{ id: 0, label: '根目录（/）', leaf: false, disabled: false }])
      return
    }
    const parentId = node.data.id === 0 ? null : node.data.id
    const res = await listChildFolders(parentId)
    const inMovedSubtree = isUnderMovedNode(node)
    resolve(
      res.data.items.map((f) => ({
        id: f.id,
        label: f.file_name,
        leaf: false,
        disabled: inMovedSubtree || f.id === props.node.id,
      })),
    )
  } catch (e) {
    resolve([])
  }
}

function onCurrentChange(data) {
  targetId.value = data?.id ?? null
}

async function confirm() {
  if (targetId.value === null) {
    ElMessage.warning('请选择目标文件夹')
    return
  }
  saving.value = true
  try {
    await moveFile(props.node.id, targetId.value === 0 ? null : targetId.value)
    ElMessage.success('移动成功')
    emit('moved')
    emit('update:modelValue', false)
  } finally {
    saving.value = false
  }
}
</script>
