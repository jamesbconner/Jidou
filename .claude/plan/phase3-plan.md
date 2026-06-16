# Phase 3: Real-Time Infrastructure (Celery + WebSockets)

## Current State

- **Celery app** in `workers/celery_app.py` — basic setup with Redis broker, JSON serialization, `task_acks_late=True`
- **One task** in `workers/tasks.py` — `fetch_trending_shows_task` with its own engine/session (task-local pattern to avoid stale pools)
- **Docker** — `jidou-worker` service already defined, depends on postgres + redis being healthy
- **Config** — `redis_url`, `celery_broker_url`, `celery_result_backend` all wired through `Settings`
- **Dependencies** — `celery[redis]`, `redis>=5.2`, `hiredis`, `websockets>=14.1` already in `pyproject.toml`

## What Phase 3 Delivers

1. **BackgroundTask model** — track Celery tasks in the DB with progress
2. **Redis PubSub progress channel** — workers publish progress; API layer subscribes and forwards to WS
3. **WebSocket endpoint** — `/ws/task-progress/{task_id}` with typed messages
4. **ConnectionManager** — track active WS connections per task_id
5. **Progress emission helper** — `emit_progress()` that workers call to push updates
6. **Task definitions** — download, scan, match, sync tasks with progress, retries, dry_run
7. **Celery hardening** — timeouts, retries, rate limits per task type

## Implementation Steps

### Step 1: Create `BackgroundTask` model

**File:** `src/jidou/models/task.py`

```python
class BackgroundTask(Base):
    id, celery_task_id (unique), task_type, status,
    progress_current, progress_total, progress_message,
    result_summary (JSONB / Text), created_at, completed_at
```

- Add to `models/__init__.py` exports
- Add to `database.py` imports (so Alembic detects)
- Create Alembic migration

**Rationale:** Every long-running operation needs DB state so the frontend can query "what happened?" even if the WS connection dropped.

### Step 2: Create `TaskRead` / `TaskProgress` Pydantic schemas

**File:** `src/jidou/schemas/task_schema.py`

- `TaskRead` — full task state for GET `/tasks/{id}`
- `TaskProgress` — slim progress snapshot for WS messages
- `TaskList` — list view with only id, task_type, status, progress_current/total, message

### Step 3: Create progress emission helper

**File:** `src/jidou/services/progress.py`

```python
async def emit_progress(redis_client, task_id: str, message: dict[str, Any]) -> None:
    await redis_client.publish("task_progress", json.dumps({...}))

async def update_task_status(session, task_id: str, status: str, ...) -> None:
    # Update BackgroundTask row
```

**Rationale:** Workers call `emit_progress()` after each unit of work (e.g., downloaded a file). The DB row is updated so the state survives restarts.

### Step 4: Create `ConnectionManager` and WebSocket endpoint

**File:** `src/jidou/api/websocket/task_progress.py`

- `ConnectionManager` — `dict[str, list[WebSocket]]` keyed by task_id
- `connect()`, `disconnect()`, `broadcast_to_task()`
- WebSocket endpoint at `/ws/task-progress/{task_id}`
- Typed messages: `{"type": "progress" | "file_update" | "complete" | "error", "data": ...}`

**File:** `src/jidou/api/websocket/__init__.py` — expose router

### Step 5: Create Redis PubSub subscriber (bridges Redis → WebSocket)

**File:** `src/jidou/services/pubsub_subscriber.py`

- Background task that subscribes to `task_progress` Redis channel
- On message, extracts `task_id`, calls `ConnectionManager.broadcast_to_task()`
- Started in FastAPI lifespan alongside `init_db()`

**Rationale:** Decouples workers from the WS layer. Workers just publish to Redis; the subscriber handles the WS forwarding.

### Step 6: Register subscriber in lifespan

**File:** `src/jidou/main.py` — update `lifespan()` to start/stop the pubsub subscriber

### Step 7: Harden Celery configuration

**File:** `src/jidou/workers/celery_app.py`

Add per-task configuration:
- `task_time_limit` — hard timeout (e.g., 3600s = 1 hour)
- `task_soft_time_limit` — SoftTimeout at 3000s so tasks can clean up
- `task_acks_late=True` already set
- `task_reject_on_worker_lost = True`

Add beat schedule (optional, for periodic tasks).

### Step 8: Create task definitions

**Files:**
- `src/jidou/workers/download_tasks.py` — download files from SFTP with progress
- `src/jidou/workers/scan_tasks.py` — scan remote SFTP for new files
- `src/jidou/workers/match_tasks.py` — match files to episodes
- `src/jidou/workers/sync_tasks.py` — full sync pipeline

Each task:
- `@shared_task(bind=True)` for self.request.id access
- Creates task-local engine/session (same pattern as `fetch_trending_shows_task`)
- Updates `BackgroundTask` row on start/progress/completion
- Calls `emit_progress()` after each unit of work
- Accepts `dry_run` parameter
- Has retry with `backend_exception_retry=True`

**Pattern:**
```python
@shared_task(bind=True)
def download_files_task(self, show_id: int, dry_run: bool = False) -> str:
    return asyncio.run(_download_files(self.request.id, show_id, dry_run))
```

### Step 9: Create tasks API route

**File:** `src/jidou/api/routes/tasks.py`

- `GET /tasks` — list background tasks
- `GET /tasks/{task_id}` — get task details
- `POST /tasks/cancel/{task_id}` — cancel a running task
- `POST /tasks/download` — trigger download (returns `task_id`)
- `POST /tasks/scan` — trigger scan
- `POST /tasks/match` — trigger matching
- `POST /tasks/sync` — trigger full sync

### Step 10: Tests

- `tests/test_websocket/` — WS connection, message format, disconnect/reconnect
- `tests/test_tasks/` — task execution with mocked SFTP/TMDB
- `tests/test_pubsub/` — progress emission and subscriber forwarding

## File Summary

| File | Purpose | Lines |
|---|---|---|
| `models/task.py` | BackgroundTask model | ~40 |
| `schemas/task_schema.py` | Task Pydantic schemas | ~50 |
| `services/progress.py` | emit_progress + DB update | ~40 |
| `api/websocket/__init__.py` | WS router export | ~5 |
| `api/websocket/task_progress.py` | ConnectionManager + WS endpoint | ~80 |
| `services/pubsub_subscriber.py` | Redis → WS bridge | ~60 |
| `workers/celery_app.py` | Hardened config | ~20 (edit) |
| `workers/download_tasks.py` | Download task | ~60 |
| `workers/scan_tasks.py` | Scan task | ~50 |
| `workers/match_tasks.py` | Match task | ~50 |
| `workers/sync_tasks.py` | Sync pipeline task | ~60 |
| `api/routes/tasks.py` | Tasks API | ~80 |
| `main.py` | Updated lifespan | ~10 (edit) |
| `models/__init__.py` | Updated exports | ~5 (edit) |
| `database.py` | Updated imports | ~3 (edit) |
| **Tests** | WS + tasks + pubsub | ~200 |
| **Total** | | **~818 lines** |
