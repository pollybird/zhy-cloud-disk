/**
 * 镜像库：better-sqlite3，存储服务端文件树快照和本地文件状态。
 * remote_nodes：上次同步完成时的服务端全树快照。
 * local_state：本地文件对应的服务端 id 和内容指纹。
 */
import Database from 'better-sqlite3'
import path from 'path'
import { app } from 'electron'

let db = null

export function initMirrorDb() {
  const dbPath = path.join(app.getPath('userData'), 'mirror.db')
  db = new Database(dbPath)
  db.pragma('journal_mode = WAL')

  db.exec(`
    CREATE TABLE IF NOT EXISTS remote_nodes (
      id INTEGER PRIMARY KEY,
      file_name TEXT NOT NULL,
      file_suffix TEXT DEFAULT '',
      file_size INTEGER DEFAULT 0,
      is_folder INTEGER DEFAULT 0,
      parent_id INTEGER,
      upload_time TEXT,
      local_path TEXT,
      last_synced_at TEXT
    );

    CREATE TABLE IF NOT EXISTS local_state (
      local_path TEXT PRIMARY KEY,
      server_id INTEGER,
      local_mtime INTEGER,
      local_size INTEGER,
      local_md5 TEXT,
      state TEXT DEFAULT 'synced'
    );

    CREATE INDEX IF NOT EXISTS idx_remote_parent ON remote_nodes(parent_id);
    CREATE INDEX IF NOT EXISTS idx_remote_local_path ON remote_nodes(local_path);
    CREATE INDEX IF NOT EXISTS idx_local_server_id ON local_state(server_id);

    CREATE TABLE IF NOT EXISTS sync_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts TEXT NOT NULL,
      action TEXT NOT NULL,
      file_name TEXT,
      local_path TEXT,
      status TEXT NOT NULL,
      message TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_sync_log_status ON sync_log(status);
  `)

  return db
}

export function getDb() {
  if (!db) initMirrorDb()
  return db
}

// ---- remote_nodes 操作 ----

export function upsertRemoteNode(node, localPath) {
  const stmt = getDb().prepare(`
    INSERT INTO remote_nodes (id, file_name, file_suffix, file_size, is_folder, parent_id, upload_time, local_path, last_synced_at)
    VALUES (@id, @file_name, @file_suffix, @file_size, @is_folder, @parent_id, @upload_time, @local_path, @last_synced_at)
    ON CONFLICT(id) DO UPDATE SET
      file_name = @file_name, file_suffix = @file_suffix, file_size = @file_size,
      is_folder = @is_folder, parent_id = @parent_id, upload_time = @upload_time,
      local_path = @local_path, last_synced_at = @last_synced_at
  `)
  stmt.run({
    id: node.id,
    file_name: node.file_name,
    file_suffix: node.file_suffix || '',
    file_size: node.file_size || 0,
    is_folder: node.is_folder ? 1 : 0,
    parent_id: node.parent_id,
    upload_time: node.upload_time,
    local_path: localPath || null,
    last_synced_at: new Date().toISOString(),
  })
}

export function getRemoteNode(id) {
  return getDb().prepare('SELECT * FROM remote_nodes WHERE id = ?').get(id)
}

export function getAllRemoteNodes() {
  return getDb().prepare('SELECT * FROM remote_nodes').all()
}

export function getRemoteNodeByPath(localPath) {
  return getDb().prepare('SELECT * FROM remote_nodes WHERE local_path = ?').get(localPath)
}

export function deleteRemoteNode(id) {
  getDb().prepare('DELETE FROM remote_nodes WHERE id = ?').run(id)
}

export function clearRemoteNodes() {
  getDb().prepare('DELETE FROM remote_nodes').run()
}

// ---- local_state 操作 ----

export function upsertLocalState(state) {
  const stmt = getDb().prepare(`
    INSERT INTO local_state (local_path, server_id, local_mtime, local_size, local_md5, state)
    VALUES (@local_path, @server_id, @local_mtime, @local_size, @local_md5, @state)
    ON CONFLICT(local_path) DO UPDATE SET
      server_id = @server_id, local_mtime = @local_mtime, local_size = @local_size,
      local_md5 = @local_md5, state = @state
  `)
  stmt.run({
    local_path: state.local_path,
    server_id: state.server_id || null,
    local_mtime: state.local_mtime || null,
    local_size: state.local_size || 0,
    local_md5: state.local_md5 || null,
    state: state.state || 'synced',
  })
}

export function getLocalState(localPath) {
  return getDb().prepare('SELECT * FROM local_state WHERE local_path = ?').get(localPath)
}

export function getLocalStateByServerId(serverId) {
  return getDb().prepare('SELECT * FROM local_state WHERE server_id = ?').get(serverId)
}

export function deleteLocalState(localPath) {
  getDb().prepare('DELETE FROM local_state WHERE local_path = ?').run(localPath)
}

export function getAllLocalStates() {
  return getDb().prepare('SELECT * FROM local_state').all()
}

export function isMirrorEmpty() {
  const row = getDb().prepare('SELECT COUNT(*) as cnt FROM remote_nodes').get()
  return row.cnt === 0
}

/**
 * 镜像是否就绪：有远端节点且有已同步的本地文件记录。
 * 防止上次首次同步中断导致"半写"状态——有远端快照但本地无文件记录，
 * 会被误判为已同步而跳过全量下载。
 */
export function isMirrorReady() {
  const remote = getDb().prepare('SELECT COUNT(*) as cnt FROM remote_nodes').get()
  const local = getDb().prepare('SELECT COUNT(*) as cnt FROM local_state WHERE server_id IS NOT NULL').get()
  return remote.cnt > 0 && local.cnt > 0
}

export function clearAllMirror() {
  getDb().prepare('DELETE FROM remote_nodes').run()
  getDb().prepare('DELETE FROM local_state').run()
}

// ---- sync_log 操作（同步历史） ----

/**
 * 记录一条同步日志。
 * @param {object} entry { action, fileName, localPath, status, message }
 */
export function addSyncLog(entry) {
  try {
    getDb()
      .prepare(
        `INSERT INTO sync_log (ts, action, file_name, local_path, status, message)
         VALUES (@ts, @action, @file_name, @local_path, @status, @message)`
      )
      .run({
        ts: new Date().toISOString(),
        action: entry.action,
        file_name: entry.fileName || null,
        local_path: entry.localPath || null,
        status: entry.status,
        message: entry.message || null,
      })
  } catch {
    // 日志失败不影响同步流程
  }
}

/**
 * 查询同步日志（倒序分页）。
 * @param {object} opts { status?: 'success'|'failed'|'skipped', limit?, offset? }
 */
export function getSyncLogs({ status, limit = 200, offset = 0 } = {}) {
  const params = { limit, offset }
  let where = ''
  if (status) {
    where = 'WHERE status = @status'
    params.status = status
  }
  const total = getDb()
    .prepare(`SELECT COUNT(*) AS cnt FROM sync_log ${where}`)
    .get(params).cnt
  const rows = getDb()
    .prepare(`SELECT * FROM sync_log ${where} ORDER BY id DESC LIMIT @limit OFFSET @offset`)
    .all(params)
  return { total, rows }
}

export function countSyncLogByStatus(status) {
  return getDb()
    .prepare('SELECT COUNT(*) AS cnt FROM sync_log WHERE status = ?')
    .get(status).cnt
}

export function clearSyncLog() {
  getDb().prepare('DELETE FROM sync_log').run()
}

export function closeMirrorDb() {
  if (db) {
    db.close()
    db = null
  }
}
