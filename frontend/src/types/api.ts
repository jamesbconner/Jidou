// ─── Shows ────────────────────────────────────────────────────────────────

export interface ShowList {
  id: number
  tmdb_id: number
  title: string
  media_type: string
  poster_path: string | null
  vote_average: number | null
  release_date: string | null
  remote_path: string | null
  local_path: string | null
  created_at: string
}

export interface ShowRead extends ShowList {
  overview: string | null
  backdrop_path: string | null
  vote_count: number
  original_language: string | null
  cached: boolean
  updated_at: string
}

export interface ShowCreate {
  tmdb_id: number
  title: string
  media_type: string
  overview?: string | null
  poster_path?: string | null
  backdrop_path?: string | null
  vote_average?: number | null
  vote_count?: number
  release_date?: string | null
  original_language?: string | null
}

export interface ShowPaths {
  remote_path?: string | null
  local_path?: string | null
}

// ─── Episodes ─────────────────────────────────────────────────────────────

export interface EpisodeList {
  id: number
  show_id: number
  season_number: number
  episode_number: number
  name: string
  air_date: string | null
  file_tracked: boolean
}

export interface EpisodeRead extends EpisodeList {
  tmdb_id: number
  overview: string | null
  runtime: number | null
  created_at: string
  updated_at: string
}

// ─── Files ────────────────────────────────────────────────────────────────

export type FileStatus =
  | 'pending'
  | 'downloading'
  | 'downloaded'
  | 'routing'
  | 'routed'
  | 'error'

export interface FileList {
  id: number
  original_filename: string
  remote_path: string
  file_size: number
  status: FileStatus
  show_id: number | null
  episode_id: number | null
  created_at: string
}

export interface FileRead extends FileList {
  local_path: string | null
  hash_sha256: string | null
  matched_by: string | null
  error_message: string | null
  updated_at: string
}

export interface FileMatchRequest {
  method: 'auto' | 'llm' | 'heuristic'
}

// ─── Tasks ────────────────────────────────────────────────────────────────

export type TaskStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type TaskType = 'download' | 'scan' | 'match' | 'sync'

export interface TaskList {
  id: number
  task_type: TaskType
  status: TaskStatus
  progress_current: number
  progress_total: number
  progress_message: string | null
  created_at: string
  completed_at: string | null
}

export interface TaskRead extends TaskList {
  celery_task_id: string
  result_summary: Record<string, unknown> | null
  dry_run: boolean
}

export interface TaskTrigger {
  task_type: TaskType
  show_id?: number | null
  dry_run?: boolean
}

// ─── WebSocket messages ───────────────────────────────────────────────────

export type WsMessageType = 'progress' | 'file_update' | 'complete' | 'error' | 'cancelled'

export interface WsProgressData {
  current: number
  total: number
  message: string
}

export interface WsFileUpdateData {
  filename: string
  action: string
}

export interface WsCompleteData {
  summary: Record<string, unknown>
}

export interface WsErrorData {
  error: string
}

export type WsMessage =
  | { type: 'progress'; data: WsProgressData }
  | { type: 'file_update'; data: WsFileUpdateData }
  | { type: 'complete'; data: WsCompleteData }
  | { type: 'error'; data: WsErrorData }
  | { type: 'cancelled'; data: Record<string, never> }

// ─── Config ───────────────────────────────────────────────────────────────

export interface AppConfig {
  app_name: string
  debug: boolean
  database_url: string | null
  redis_url: string | null
  tmdb_api_key_set: boolean
  tmdb_base_url: string
  sftp_host: string | null
  sftp_port: number
  sftp_username: string | null
  llm_provider: string
  llm_model: string
  llm_base_url: string | null
}

export interface ConnectionTestResult {
  ok: boolean
  error?: string
  message?: string
}

// ─── Admin ────────────────────────────────────────────────────────────────

export interface AdminStats {
  shows: number
  episodes: number
  downloaded_files: number
  watchlist: number
  background_tasks: number
}

export interface ServiceHealth {
  ok: boolean
  configured?: boolean
  latency_ms?: number
  error?: string
}

export interface HealthCheck {
  healthy: boolean
  services: {
    database: ServiceHealth
    redis: ServiceHealth
    tmdb: ServiceHealth
  }
}

export interface CacheEntry {
  label: string
  key: string
}

export interface CacheStats {
  count: number
  maxsize: number
  ttl_seconds: number
  entries: CacheEntry[]
}

// ─── Watchlist ────────────────────────────────────────────────────────────

export type WatchlistStatus = 'planned' | 'watching' | 'completed' | 'on_hold' | 'dropped'

export interface WatchlistList {
  id: number
  show_id: number
  status: WatchlistStatus
  position: number
  created_at: string
}

export interface WatchlistRead extends WatchlistList {
  notes: string | null
  updated_at: string
}

export interface WatchlistCreate {
  show_id: number
  status?: WatchlistStatus
  notes?: string | null
  position?: number
}

export interface WatchlistUpdate {
  status?: WatchlistStatus | null
  notes?: string | null
  position?: number | null
}

// ─── File PATCH ───────────────────────────────────────────────────────────

export interface FilePatch {
  show_id?: number | null
  episode_id?: number | null
  status?: FileStatus | null
  error_message?: string | null
}

// ─── TMDB raw responses (proxied through backend) ─────────────────────────

export interface TmdbResult {
  id: number
  title?: string
  name?: string
  overview: string
  poster_path: string | null
  backdrop_path: string | null
  vote_average: number
  vote_count: number
  release_date?: string
  first_air_date?: string
  media_type?: string
  original_language: string
}

export interface TmdbSearchResponse {
  results: TmdbResult[]
  total_results: number
  total_pages: number
  page: number
}
