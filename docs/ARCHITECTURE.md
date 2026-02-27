# G2 Architecture

System architecture for G2 — a personal Claude assistant running in isolated containers.

---

## Overview

G2 is a single Python process that:

1. Connects to messaging channels (WhatsApp, Gmail, extensible to Telegram/Discord)
2. Polls SQLite for new messages every 2 seconds
3. Spawns isolated Docker containers running the Claude Agent SDK
4. Streams agent output back to users
5. Handles IPC commands from containers (scheduling, messaging, session management)

Each registered group gets its own container with isolated filesystem, session state, and IPC namespace.

```
WhatsApp ──> SQLite ──> Polling Loop ──> Container (Claude Agent SDK) ──> Response
                              │
                        Task Scheduler ──> Container ──> IPC send_message
```

---

## Layers

### 1. Channel Ingestion

Channels implement the `Channel` Protocol (`connect`, `send_message`, `is_connected`, `owns_jid`). `ChannelRegistry` holds all channels and routes outbound messages by JID pattern.

| JID Pattern | Channel |
|---|---|
| `*@g.us`, `*@s.whatsapp.net` | WhatsApp |
| `gmail:*` | Gmail |
| `tg:*` | Telegram |
| `dc:*` | Discord |

**WhatsApp specifics:**
- neonize library (Python bindings for whatsmeow/Go) for WhatsApp Web connection
- LID-to-phone JID translation for consistency
- Bot messages detected via `is_from_me` flag (own number) or prefix matching (shared number)
- `OutgoingMessageQueue` buffers messages during disconnection, flushes on reconnect
- `WhatsAppMetadataSync` caches group names with 24h TTL

### 2. Message Loop

`MessageProcessor.start_polling()` in `src/g2/messaging/poller.py` runs every `POLL_INTERVAL` (2s):

1. `get_new_messages()` fetches messages since `last_timestamp` from SQLite
2. Deduplicates by group (one container invocation per group per cycle)
3. **Trigger check**: main group always active; other groups require `@G2` mention (configurable regex)
4. Fetches ALL messages since `last_agent_timestamp[group]` for full context
5. `format_messages()` converts to XML: `<message sender="Alice">Hello</message>`
6. Enqueues via `GroupQueue`

**Cursor management** (exactly-once processing):
- `last_timestamp` — global polling cursor, advanced after reading
- `last_agent_timestamp[group]` — per-group cursor, advanced **before** running agent
- On error before user output: cursor rolled back for retry
- On error after user output: cursor kept (prevents duplicate responses)

### 3. Concurrency and Queuing

`GroupQueue` enforces per-group ordering with a global concurrency limit.

| Setting | Default | Purpose |
|---|---|---|
| `MAX_CONCURRENT_CONTAINERS` | 5 | Max containers running simultaneously |
| Retry backoff | 5s, 10s, 20s, 40s, 80s | Exponential, max 5 retries |

**State machine per group:** idle -> active -> processing -> idle

- Tasks are prioritized over messages (tasks won't be rediscovered from DB)
- When concurrency limit is hit, groups queue in a waiting list
- `_drain_waiting()` processes the first waiting group when a slot opens

**Interactive pipelining:** follow-up messages pipe to a running container's IPC input directory rather than spawning a new container.

### 4. Container Execution

Each agent runs in an isolated Docker container (`g2-agent:latest`):

```
docker run -i --rm \
  -e TZ={timezone} \
  -v groups/{folder}:/workspace/group \
  -v data/ipc/{folder}:/workspace/ipc \
  -v data/sessions/{folder}/.claude:/home/agent/.claude \
  ... \
  g2-agent:latest
```

**Container image:** Python 3.12-slim + Chromium + Node.js + `@anthropic-ai/claude-code`

**Input:** JSON via stdin containing `prompt`, `sessionId`, `groupFolder`, `chatJid`, `isMain`, and `secrets`

**Output:** Streaming results via sentinel markers (`---G2_OUTPUT_START---` / `---G2_OUTPUT_END---`)

**Inside the container** (`container/agent-runner/src/main.py`):
- Reads stdin JSON, runs Claude Code CLI with follow-up message polling
- `MessageStream` polls `/workspace/ipc/input/` for follow-up messages
- Polls for `_close` sentinel to gracefully exit

**Timeouts:**

| Timeout | Default | Behavior |
|---|---|---|
| Idle | 30 min | No output -> host writes `_close` sentinel -> graceful exit |
| Hard | idle + 30s | `docker stop` -> `SIGKILL` fallback |
| Per-group override | `container_config.timeout` | Configured per registered group |

Activity-based reset: each `OUTPUT_START_MARKER` in stdout resets the hard timeout.

### 5. Per-Group Isolation

**Main group mounts:**

| Host Path | Container Path | Access |
|---|---|---|
| Project root | `/workspace/project` | read-write |
| `groups/main/` | `/workspace/group` | read-write |
| `data/ipc/main/` | `/workspace/ipc` | read-write |
| `data/sessions/main/.claude/` | `/home/agent/.claude` | read-write |
| `~/.aws/` | `/home/agent/.aws` | read-only (if exists) |

**Non-main group mounts:**

| Host Path | Container Path | Access |
|---|---|---|
| `groups/{folder}/` | `/workspace/group` | read-write |
| `groups/global/` | `/workspace/global` | read-only |
| `data/ipc/{folder}/` | `/workspace/ipc` | read-write |
| `data/sessions/{folder}/.claude/` | `/home/agent/.claude` | read-write |
| `~/.aws/` | `/home/agent/.aws` | read-only (if exists) |

Non-main groups cannot see other groups' data, the project root, or the database.

Additional mounts are validated against the mount allowlist (`~/.config/g2/mount-allowlist.json`) and can be forced read-only via the `non_main_read_only` flag.

### 6. IPC (Container <-> Host)

File-based IPC through bind-mounted directories. The host uses `watchfiles` for event-driven processing, plus a 10-second fallback poll for reliability.

**Container -> Host:**

| Directory | Purpose |
|---|---|
| `/workspace/ipc/messages/` | Outbound messages -> auth check -> `channel.send_message()` |
| `/workspace/ipc/tasks/` | Commands -> `IpcCommandDispatcher` -> handler |

**Host -> Container:**

| Directory | Purpose |
|---|---|
| `/workspace/ipc/input/` | Follow-up messages, `_close` sentinel |

**Available IPC commands:**

| Command | Access | Purpose |
|---|---|---|
| `send_message` | Own group (main: any) | Send message to user/group |
| `schedule_task` | Own group (main: any) | Create cron/interval/once task |
| `pause_task` | Own tasks (main: any) | Temporarily disable task |
| `resume_task` | Own tasks (main: any) | Re-enable paused task |
| `cancel_task` | Own tasks (main: any) | Permanently delete task |
| `register_group` | Main only | Register new group |
| `refresh_groups` | Main only | Re-sync WhatsApp metadata |
| `clear_session` | Own session (main: any) | Archive and reset session |
| `resume_session` | Own session (main: any) | Restore archived session |
| `search_sessions` | Own session (main: any) | Query archived sessions |
| `archive_session` | Own session (main: any) | Archive current transcript |

Commands are dispatched by `IpcCommandDispatcher` to modular handlers in `src/g2/ipc/handlers/`.

### 7. Task Scheduling

`start_scheduler_loop()` polls SQLite every `SCHEDULER_POLL_INTERVAL` (60s) for due tasks:

```sql
SELECT * FROM scheduled_tasks WHERE status='active' AND next_run IS NOT NULL AND next_run <= ?
```

Tasks are atomically claimed via `claim_task()` (sets `next_run = NULL`) to prevent duplicate execution when tasks run longer than 60s. See [HEARTBEAT.md](HEARTBEAT.md) for the full lifecycle.

**Schedule types:**
- `cron` — standard cron expressions, parsed with `croniter` and timezone awareness
- `interval` — milliseconds between runs
- `once` — single execution at ISO timestamp

**Context modes:**
- `group` — task receives current chat history (via Claude Agent SDK session)
- `isolated` — fresh session without history

Tasks execute in containers via `GroupQueue`, respecting concurrency limits. After execution:
1. Calculate `next_run` based on schedule type
2. Log run to `task_run_logs` (duration, status, result, error)
3. If no `next_run`, set status to `completed`

Scheduled task output is not sent to users automatically — the agent must use `send_message`.

### 8. Session Management

`SessionManager` maps `group_folder -> Claude Agent SDK session_id`.

- Sessions persist in SQLite across restarts
- Each group has isolated session data at `data/sessions/{folder}/.claude/`
- Skills synced from `container/skills/` into each group's `.claude/skills/`
- Agents can archive/restore sessions via IPC (`clear_session`, `resume_session`)
- Session history enables named conversation snapshots

### 9. Authorization

Role-based authorization enforced at every IPC boundary (`src/g2/groups/authorization.py`). The `AuthorizationPolicy` class encapsulates checks for a single source context.

| Operation | Main Group | Non-Main Group |
|---|---|---|
| Send message to own group | yes | yes |
| Send message to other group | yes | no |
| Schedule task for other group | yes | no |
| Manage other group's tasks | yes | no |
| Register new group | yes | no |
| Refresh group metadata | yes | no |
| Manage other group's sessions | yes | no |

Auth context: `AuthContext(source_group=str, is_main=bool)`

### 10. Security

**Secrets:** Read from `.env` via `read_env_file()`, passed to container via stdin only, removed from input object after write. Never in `os.environ`, never on disk in mounted paths.

**Mount allowlist:** Stored at `~/.config/g2/mount-allowlist.json` (outside project root, unreachable by containers). Validates against blocked patterns (`.ssh`, `.gnupg`, `.env`, credentials, private keys). Resolves symlinks to prevent path traversal.

**Container hardening:** Non-root user (`agent:1000`), no `--privileged`, source code mounted read-only.

### 11. Data Persistence

SQLite database (`store/messages.db`). Containers have no direct DB access — all data flows through the host. `AppDatabase` in `src/g2/infrastructure/database.py` is a thin composition root that delegates to domain-specific repositories (chat, message, task, session, group, state).

| Table | Purpose |
|---|---|
| `chats` | Chat metadata (JID, name, last_message_time, channel, is_group) |
| `messages` | Full message history for registered groups |
| `registered_groups` | Group config (JID, folder, trigger, containerConfig) |
| `scheduled_tasks` | Task definitions (schedule_type, next_run, status) |
| `task_run_logs` | Execution history per task run |
| `sessions` | Active Claude session ID per group |
| `conversation_archives` | Archived sessions for restore |
| `router_state` | Polling cursors (last_timestamp, last_agent_timestamp) |

---

## Startup Sequence

`run()` in `src/g2/__main__.py` calls `asyncio.run(main())` which creates the `Orchestrator` and calls `orchestrator.start()`:

```
main() [src/g2/__main__.py]
  1. Create Orchestrator
  2. Set up signal handlers (SIGTERM, SIGINT)
  3. orchestrator.start()
  4. Wait for shutdown signal

Orchestrator.start() [src/g2/app.py]
  1. init database                     — create/migrate SQLite
  2. Load registered groups from DB
  3. Initialize SessionManager, TaskManager, SnapshotWriter
  4. Create ContainerRunner, AgentExecutor
  5. Create MessageProcessor           — composed service
  6. messageProcessor.load_state()     — restore cursors from DB
  7. Set up channels                   — WhatsApp (neonize), Gmail (google-api)
  8. Start IpcWatcher                  — watchfiles + 10s fallback poll
  9. Start scheduler loop              — 60s task polling
 10. Start message polling             — 2s message polling
 11. Recover pending messages          — re-queue unprocessed from crash
```

## Crash Recovery

- On startup, `MessageProcessor.recover_pending_messages()` checks each registered group for unprocessed messages
- If `last_agent_timestamp[group]` has unprocessed messages, they are re-queued immediately
- Handles the gap between advancing `last_timestamp` and completing agent processing

## Output Processing

Agent output flows through `src/g2/messaging/formatter.py`:
- `strip_internal_tags()` strips `<internal>...</internal>` tags (agent reasoning hidden from users)
- `_xml_escape()` prevents XML injection in inbound message formatting
- Empty strings after stripping are discarded (no empty messages sent)

---

## Key Design Patterns

| Pattern | Implementation |
|---|---|
| Cursor-based exactly-once | Advance before processing, roll back on pre-output errors |
| Per-group isolation | Separate filesystem, session, IPC namespace, cursor per group |
| Fair scheduling | Global concurrency limit + per-group queue, no starvation |
| Streaming output | Agent results sent immediately via sentinel markers |
| Channel abstraction | `Channel` Protocol + `ChannelRegistry` for pluggable transports |
| File-based IPC | Atomic JSON file writes, `watchfiles` + fallback poll, no sockets |
| Composed services | `AgentExecutor` (container execution), `MessageProcessor` (polling + cursors), `Orchestrator` (wiring) |
| Repository pattern | Domain-specific DB classes behind `AppDatabase` composition root |
| Shared utilities | `start_poll_loop`, `IdleTimer`, `IpcTransport`, `SnapshotWriter`, `GroupPaths` |
| Untrusted containers | Host validates every IPC command before acting |
| Protocols over ABCs | `typing.Protocol` for structural subtyping (Channel, ContainerRuntime, MountFactory) |
