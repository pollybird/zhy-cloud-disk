/**
 * 按本地目录结构把文件上传到部门网盘（渲染层编排，无 Node 内置依赖）。
 *
 * groups 形态：
 *   { rootName: null, files: ['/选的散文件/a.doc'] }
 *   { rootName: '项目资料', files: ['/拖入/项目资料/需求.doc', '/拖入/项目资料/子目录/x.pdf'] }
 *
 * 目录组会在当前部门目录下重建同名文件夹及其子目录；散文件直传当前目录。
 * 同名异内容冲突统一询问一次，决定对全部冲突生效。
 */
import { splitSegments } from './drag-drop.js'

function basename(p) {
  const segs = splitSegments(p)
  return segs[segs.length - 1] || p
}

function dirnameSegments(p) {
  return splitSegments(p).slice(0, -1)
}

/**
 * @param {Array<{rootName:string|null, files:string[]}>} groups
 * @param {object} ctx
 * @param {number} ctx.departmentId
 * @param {number|null} ctx.parentId 当前浏览的部门文件夹 id
 * @param {(parentId:number|null)=>Promise<Array<{id:number,file_name:string}>>} ctx.listFolders
 * @param {(parentId:number|null,name:string)=>Promise<{id:number}>} ctx.createFolder
 * @param {(paths:string[],parentId:number|null)=>Promise<Array>} ctx.plan
 * @param {(plans:Array,parentId:number|null,overwrite:boolean)=>Promise<{success:Array,skipped:Array,failed:Array}>} ctx.upload
 * @param {(conflictCount:number)=>Promise<boolean>} ctx.askOverwrite
 * @returns {Promise<{success:number, skipped:number, failed:Array, conflict:number}>}
 */
export async function uploadGroupsToDept(groups, ctx) {
  const {
    departmentId,
    parentId,
    listFolders,
    createFolder,
    plan,
    upload,
    askOverwrite,
  } = ctx

  // 同一次上传内目录 id 缓存，避免重复查询/创建
  const folderCache = new Map()
  async function ensureFolder(parent, name) {
    const key = `${parent ?? 'root'}::${name}`
    if (folderCache.has(key)) return folderCache.get(key)
    let id = null
    try {
      const siblings = await listFolders(parent)
      id = (siblings || []).find((f) => f.file_name === name)?.id ?? null
    } catch {
      // 查询失败则尝试直接创建，由服务端判重
    }
    if (!id) {
      const node = await createFolder(parent, name)
      id = node.id
    }
    folderCache.set(key, id)
    return id
  }

  // 第一阶段：解析每个文件的目标文件夹，并确保远端目录存在
  /** @type {Array<{parent:number|null, files:string[]}>} */
  const buckets = []
  const bucketIndex = new Map()
  const bucketKey = (p) => String(p)

  async function addBucket(parent, files) {
    const key = bucketKey(parent)
    let bucket = bucketIndex.get(key)
    if (!bucket) {
      bucket = { parent, files: [] }
      bucketIndex.set(key, bucket)
      buckets.push(bucket)
    }
    bucket.files.push(...files)
  }

  for (const group of groups) {
    if (!group.rootName) {
      // 散文件 → 当前目录
      // eslint-disable-next-line no-await-in-loop
      await addBucket(parentId, group.files)
      continue
    }
    // 目录组 → 重建目录结构
    const rootId = await ensureFolder(parentId, group.rootName)
    const subdirCache = new Map()
    for (const f of group.files) {
      const dirSegs = dirnameSegments(f)
      const rootIdx = dirSegs.lastIndexOf(group.rootName)
      const relSegs = rootIdx >= 0 ? dirSegs.slice(rootIdx + 1) : []
      const relKey = relSegs.join('/')
      let target = subdirCache.get(relKey)
      if (!target) {
        target = rootId
        // eslint-disable-next-line no-await-in-loop
        for (const seg of relSegs) {
          target = await ensureFolder(target, seg)
        }
        subdirCache.set(relKey, target)
      }
      // eslint-disable-next-line no-await-in-loop
      await addBucket(target, [f])
    }
  }

  // 第二阶段：每个桶查重
  const planned = []
  for (const bucket of buckets) {
    // eslint-disable-next-line no-await-in-loop
    const plans = await plan(bucket.files, bucket.parent)
    for (const p of plans) planned.push({ ...p, parent: bucket.parent })
  }

  const conflictCount = planned.filter((p) => p.action === 'conflict').length
  let overwrite = false
  if (conflictCount > 0) {
    overwrite = await askOverwrite(conflictCount)
  }

  // 第三阶段：按桶执行上传
  let success = 0
  let skipped = 0
  const failed = []
  for (const bucket of buckets) {
    const plans = planned.filter((p) => p.parent === bucket.parent)
    // eslint-disable-next-line no-await-in-loop
    const res = await upload(plans, bucket.parent, overwrite)
    success += res.success?.length || 0
    skipped += res.skipped?.length || 0
    for (const f of res.failed || []) failed.push(f)
  }

  return { success, skipped, failed, conflict: conflictCount }
}

export { basename }
