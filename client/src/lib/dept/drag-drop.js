/**
 * 拖拽上传路径收集（渲染层纯逻辑，不使用 Node 内置模块）。
 *
 * Electron 32+ 移除了 File.path，渲染层必须通过 preload 暴露的
 * webUtils.getPathForFile(file) 取拖入文件的真实路径；
 * 目录是否为目录、目录递归枚举均由主进程 IPC 完成（渲染层无 fs 权限）。
 */

/** 按 / 或 \\ 切分路径段（同时兼容 Windows 与 POSIX 路径）。 */
export function splitSegments(p) {
  return String(p).split(/[\\/]/).filter(Boolean)
}

/** ancestor 是否为 p 自身或其父目录（盘符/大小写不敏感比较）。 */
export function isAncestorOrEqual(ancestor, p) {
  const a = splitSegments(ancestor)
  const b = splitSegments(p)
  if (a.length > b.length) return false
  return a.every((seg, i) => seg.toLowerCase() === b[i]?.toLowerCase())
}

/** 同一批路径中，丢弃被目录祖先覆盖的子路径（如同时拖入 /a 与 /a/b.txt 时保留 /a）。 */
export function dedupeNested(paths) {
  return paths.filter((p) => !paths.some((q) => q !== p && isAncestorOrEqual(q, p)))
}

/** 从 DataTransferFile 列表取出去重后的本地路径。 */
export function collectDroppedPaths(fileList, getPathForFile) {
  const raw = []
  const list = Array.from(fileList || [])
  for (const file of list) {
    const p = getPathForFile(file)
    if (p) raw.push(p)
  }
  return dedupeNested(raw)
}

/**
 * 完整收集拖入项对应的全部待上传文件：
 * 文件直接保留，目录递归展开，再整体去嵌套。
 *
 * @param {DataTransfer} dataTransfer
 * @param {object} deps 由 preload 注入的主进程能力
 * @param {(file:File)=>string} deps.getPathForFile
 * @param {(paths:string[])=>Promise<{files:string[],dirs:string[]}>} deps.statPaths
 * @param {(dir:string)=>Promise<string[]>} deps.walkDir 递归返回目录内全部文件
 * @returns {Promise<string[]>}
 */
export async function gatherUploadFiles(dataTransfer, { getPathForFile, statPaths, walkDir }) {
  const raw = collectDroppedPaths(dataTransfer?.files, getPathForFile)
  if (raw.length === 0) return []
  const { files = [], dirs = [] } = await statPaths(raw)
  const expanded = await Promise.all(dirs.map((d) => walkDir(d)))
  return dedupeNested([...files, ...expanded.flat()])
}

function pathBasename(p) {
  const segs = splitSegments(p)
  return segs[segs.length - 1] || p
}

/**
 * 收集拖入项并保留目录分组（供结构化上传）：
 * 散文件归为 rootName=null 的一组；每个拖入目录各成一组（含递归文件）。
 *
 * @returns {Promise<Array<{rootName:string|null, files:string[]}>>}
 */
export async function collectDropEntries(dataTransfer, { getPathForFile, statPaths, walkDir }) {
  const raw = collectDroppedPaths(dataTransfer?.files, getPathForFile)
  if (raw.length === 0) return []
  const { files = [], dirs = [] } = await statPaths(raw)
  const groups = []
  if (files.length > 0) groups.push({ rootName: null, files })
  await Promise.all(
    dirs.map(async (d) => {
      const inner = await walkDir(d)
      if (inner.length > 0) groups.push({ rootName: pathBasename(d), files: inner })
    })
  )
  return groups
}
