// ─── Shows ────────────────────────────────────────────────────────────────

export interface TmdbGenre {
  id: number
  name: string
}

export interface TmdbNetwork {
  id: number
  name: string
  logo_path: string | null
  origin_country: string
}

export interface ShowList {
  id: number
  tmdb_id: number
  title: string
  media_type: string
  poster_path: string | null
  vote_average: number | null
  release_date: string | null
  content_type: string | null
  sys_name: string | null
  genres: TmdbGenre[] | null
  origin_country: string[] | null
  last_air_date: string | null
  last_episode_to_air: Record<string, unknown> | null
  next_episode_to_air: Record<string, unknown> | null
  homepage: string | null
  external_ids: Record<string, unknown> | null
  episode_groups: Record<string, unknown>[] | null
  status: string | null
  in_production: boolean | null
  number_of_seasons: number | null
  number_of_episodes: number | null
  networks: TmdbNetwork[] | null
  show_type: string | null
  runtime: number | null
  tagline: string | null
  original_language: string | null
  local_path: string | null
  episode_count: number
  matched_file_count: number
  created_at: string
}

export interface ShowRead extends ShowList {
  overview: string | null
  backdrop_path: string | null
  vote_count: number
  cached: boolean
  aliases: string[] | null
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
  genres?: TmdbGenre[] | null
  origin_country?: string[] | null
  last_air_date?: string | null
  last_episode_to_air?: Record<string, unknown> | null
  next_episode_to_air?: Record<string, unknown> | null
  homepage?: string | null
  external_ids?: Record<string, unknown> | null
  episode_groups?: Record<string, unknown>[] | null
  status?: string | null
  in_production?: boolean | null
  number_of_seasons?: number | null
  number_of_episodes?: number | null
  networks?: TmdbNetwork[] | null
  show_type?: string | null
  runtime?: number | null
  tagline?: string | null
  genre_ids?: number[] | null
  content_type?: string | null
}

export interface ShowPaths {
  local_path?: string | null
}

export interface ShowPatch {
  content_type?: string | null
}

// ─── Episodes ─────────────────────────────────────────────────────────────

export interface BackingFile {
  id: number
  filename: string
}

export interface EpisodeList {
  id: number
  show_id: number
  season_number: number
  episode_number: number
  name: string
  air_date: string | null
  episode_type: string | null
  absolute_episode_number: number | null
  file_tracked: boolean
  tracked_filename: string | null
  tracked_source: 'match' | 'import' | null
  backing_files: BackingFile[]
}

export interface EpisodeRead extends EpisodeList {
  tmdb_id: number
  overview: string | null
  runtime: number | null
  still_path: string | null
  created_at: string
  updated_at: string
}

// ─── Files ────────────────────────────────────────────────────────────────

export interface ShowBrief {
  id: number
  title: string
}

export interface EpisodeBrief {
  id: number
  season_number: number
  episode_number: number
  name: string
}

export type FileStatus =
  | 'pending'
  | 'discovered'
  | 'downloading'
  | 'downloaded'
  | 'unmatched'
  | 'matched'
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
  parsed_show_name: string | null
  created_at: string
}

export interface FileRead extends FileList {
  local_path: string | null
  hash_sha256: string | null
  matched_by: string | null
  error_message: string | null
  parsed_season: number | null
  parsed_episode: number | null
  parsed_confidence: number | null
  parsed_content_type: string | null
  updated_at: string
  show: ShowBrief | null
  episode: EpisodeBrief | null
}

export type ContentType = 'tv' | 'anime' | 'movie'

export interface FileMatchRequest {
  show_id?: number | null
  tmdb_id?: number | null
  tmdb_media_type?: 'tv' | 'movie' | null
  local_path?: string | null
  content_type?: ContentType | null
}

export interface TmdbSuggestion {
  tmdb_id: number
  title: string | null
  media_type: string | null
  overview: string | null
  poster_path: string | null
  first_air_date: string | null
  vote_average: number | null
}

export interface TmdbSuggestionsResponse {
  query: string
  results: TmdbSuggestion[]
}

// ─── Tasks ────────────────────────────────────────────────────────────────

export type TaskStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type TaskType = 'download' | 'scan' | 'match' | 'route' | 'sync' | 'import' | 'db_import'

export interface TaskList {
  id: number
  task_type: TaskType
  status: TaskStatus
  progress_current: number
  progress_total: number
  progress_message: string | null
  result_summary: Record<string, unknown> | null
  dry_run: boolean
  created_at: string
  completed_at: string | null
}

export interface TaskRead extends TaskList {
  celery_task_id: string
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
  local_tv_path: string
  local_anime_path: string
  local_movie_path: string
}

export interface ConnectionTestResult {
  ok: boolean
  error?: string
  message?: string
}

// ─── Admin ────────────────────────────────────────────────────────────────

export interface AdminStats {
  shows: number
  episodes_tracked: number
  episodes_total: number
  files_needs_attention: number
  files_added_1d: number
  files_added_7d: number
  files_added_30d: number
  watchlist: number
  background_tasks: number
  dq_total: number
  dq_no_path: number
  dq_no_content_type: number
  dq_no_episodes: number
  dq_orphan: number
}

export interface FileTimelineEntry {
  date: string
  count: number
}

export interface PipelineStatusEntry {
  status: string
  count: number
}

export interface ServiceHealth {
  ok: boolean
  configured?: boolean
  latency_ms?: number
  error?: string
  provider?: string
  model?: string
}

export interface HealthCheck {
  healthy: boolean
  services: {
    database: ServiceHealth
    redis: ServiceHealth
    tmdb: ServiceHealth
    llm: ServiceHealth
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

export interface WatchlistShowBrief {
  title: string
  tmdb_id: number
  poster_path: string | null
}

export interface WatchlistList {
  id: number
  show_id: number
  show: WatchlistShowBrief
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

// ─── Orphaned Tracking Records ────────────────────────────────────────────

export interface OrphanedTrackingRecord {
  id: number
  show_id: number
  show_title: string
  tracked_filename: string | null
  tracked_source: 'match' | 'import'
  old_season_number: number
  old_episode_number: number
  downloaded_file_id: number | null
  created_at: string
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
  genre_ids?: number[] | null
  origin_country?: string[] | null
}

export interface TmdbSearchResponse {
  results: TmdbResult[]
  total_results: number
  total_pages: number
  page: number
}

// ─── Path Import ──────────────────────────────────────────────────────────────

export interface ShowImportResult {
  show_dir: string
  tmdb_id: number | null
  tmdb_title: string | null
  action: 'created' | 'found' | 'not_found'
  episodes_tracked: number
  episodes_unmatched: number
}

export interface PathImportResult {
  shows_processed: number
  shows_created: number
  shows_found: number
  shows_not_found: number
  episodes_tracked: number
  episodes_unmatched: number
  show_results: ShowImportResult[]
}
