# G2 Memory System

How conversation state is stored, resumed, archived, and searched.

---

## Overview

The memory system has two layers:

1. **Claude Agent SDK sessions** — the actual conversation state the agent has access to during a query
2. **SQLite tables** — track which session is active per group (`sessions`) and store archived conversations with searchable content (`conversation_archives`)

```
┌─────────────────────────────────────────────────────────────┐
│  data/sessions/{group}/.claude/                             │
│  ├── projects/-workspace-group/                             │
│  │   ├── {sessionId-A}.jsonl   ← full/compacted transcript  │
│  │   ├── {sessionId-B}.jsonl                                │
│  │   └── {sessionId-C}.jsonl                                │
│  ├── session-env/{sessionId}/  ← environment state          │
│  ├── todos/                    ← task tracking              │
│  ├── shell-snapshots/          ← Bash tool state            │
│  └── settings.json             ← SDK config + feature flags │
│                                                             │
│  (All sessions for a group coexist in one .claude/ dir,     │
│   each keyed by UUID. The SDK loads whichever sessionId     │
│   is passed via the `resume` parameter.)                    │
└─────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────┐
│  SQLite (store/messages.db)              │
│                                          │
│  sessions table                          │
│  ┌────────────┬──────────────────┐       │
│  │group_folder│ session_id       │       │
│  ├────────────┼──────────────────┤       │
│  │ main       │ d58a79a7-...     │  ← active session pointer
│  │ dev-team   │ 7b8ff97a-...     │       │
│  └────────────┴──────────────────┘       │
│                                          │
│  conversation_archives table             │
│  ┌──┬────────────┬──────────────┬──────┬─────────┐
│  │id│group_folder│ session_id   │ name │ content │
│  ├──┼────────────┼──────────────┼──────┼─────────┤
│  │ 2│ main       │ 5768e1ec-... │ "Tax"│ "# T.."│ ← archived with transcript
│  │ 3│ main       │ 40b21204-... │ "..." │ "# .."│
│  └──┴────────────┴──────────────┴──────┴─────────┘
└──────────────────────────────────────────┘
```

### What was removed

- **`session_history` table** — replaced by `conversation_archives` (which adds `content` column for searchable transcripts)
- **`conversations/` folder** — markdown transcript files are no longer written to disk; content is stored in the `conversation_archives` table instead

---

## Layer 1: Claude Agent SDK Sessions

### What a session is

A session is identified by a UUID string (e.g. `d58a79a7-451e-4af5-86d1-3e839200d98d`). It represents the full conversation state managed by the Claude Agent SDK — the compacted transcript, tool results, environment state, and todos.

### Where sessions live on disk

All sessions for a group are stored under a single `.claude/` directory:

```
data/sessions/{group}/.claude/
├── projects/-workspace-group/
│   ├── {sessionId}.jsonl          # Conversation transcript (JSONL format)
│   └── {sessionId}/tool-results/  # Cached tool outputs
├── session-env/{sessionId}/       # Per-session environment state
├── todos/{sessionId}-agent-*.json # Per-session task tracking
├── shell-snapshots/               # Bash tool shell state (shared)
├── debug/                         # Debug logs
├── plans/                         # Plan mode artifacts
├── skills/                        # Synced from container/skills/
└── settings.json                  # SDK feature flags
```

The `-workspace-group` directory name is derived from the container's cwd (`/workspace/group`), encoded by the SDK.

### Multiple sessions coexist

The `.claude/` directory is **not** one session per group. Every session that has ever existed for that group has its `.jsonl` transcript file here, keyed by UUID. The SDK loads whichever session ID is passed via the `resume` parameter in `query()`. Old session files remain on disk indefinitely.

### How sessions are mounted

`MountBuilder` (`src/g2/execution/mount_builder.py`) mounts the group's `.claude/` directory into the container:

```
Host: data/sessions/{group}/.claude/
  → Container: /home/agent/.claude/
```

On first mount, a `settings.json` is initialized with feature flags (agent teams, additional directories, auto memory).

### How sessions are resumed

In `container/agent-runner/src/main.py`, the SDK `query()` call receives:

```python
query(
    prompt=stream,
    options={
        "resume": session_id,        # UUID from sessions table, or None for new
        "resume_session_at": resume_at,  # Resume at specific message UUID
        "cwd": "/workspace/group",
    }
)
```

When `resume` is `undefined`, the SDK creates a new session and returns the new UUID via the `system/init` message. When `resume` is set, the SDK loads the corresponding `.jsonl` transcript.

### Compaction

When the conversation grows too long for the context window, the SDK automatically **compacts** the transcript — older messages are summarized and the `.jsonl` is rewritten with compacted content. After compaction, the original verbatim messages are lost from the SDK state. The `PreCompact` hook captures the full transcript before this happens and stores it in `conversation_archives` via IPC.

---

## Layer 2: SQLite Tables

The SQLite database stores **pointers** (which session UUID is active for each group) and **archived conversations** with searchable content.

### `sessions` table

```sql
CREATE TABLE sessions (
  group_folder TEXT PRIMARY KEY,
  session_id TEXT NOT NULL
);
```

Maps each group to its currently active session UUID. This is what `SessionManager.get()` returns, and what gets passed as `resume` to the SDK.

### `conversation_archives` table

```sql
CREATE TABLE conversation_archives (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  group_folder TEXT NOT NULL,
  session_id TEXT NOT NULL,
  name TEXT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  archived_at TEXT NOT NULL
);
CREATE INDEX idx_archives_group ON conversation_archives(group_folder);
```

Stores archived conversations with both the session UUID (for resuming) and the full transcript content (for searching). Used by `list_sessions`, `search_sessions`, and `resume_session`.

### `SessionManager` (`src/g2/sessions/manager.py`)

In-memory cache backed by SQLite. Provides:

| Method | Purpose |
|---|---|
| `get(groupFolder)` | Return active session UUID |
| `set(groupFolder, sessionId)` | Set active session (memory + DB) |
| `delete(groupFolder)` | Remove active session pointer |
| `getAll()` | Return all active sessions |
| `loadFromDb()` | Load all sessions from DB into memory |

### Database accessor functions (`src/g2/infrastructure/database.py`)

| Function | Purpose |
|---|---|
| `insertConversationArchive(groupFolder, sessionId, name, content, archivedAt)` | Archive a conversation with transcript |
| `getConversationArchives(groupFolder)` | List archives for a group (no content, for snapshots) |
| `getConversationArchiveById(id)` | Get a single archive with content |
| `searchConversationArchives(groupFolder, query)` | Full-text search archives by content |
| `deleteConversationArchive(id)` | Remove an archive (when resumed) |

### Snapshot pattern

Containers have no direct DB access. Before each container spawn, the host writes a JSON snapshot of the conversation archives to `data/ipc/{group}/session_history.json`. The `list_sessions` MCP tool reads this file. Same pattern used for `current_tasks.json` and `available_groups.json`.

### IPC round-trip pattern (search_sessions)

For `search_sessions`, the container needs a response from the host. This uses an IPC round-trip:

1. Container writes request to `tasks/` with a `requestId`
2. Host `SearchSessionsHandler` queries the DB and writes the result to `responses/{requestId}.json`
3. Container polls `responses/{requestId}.json` until it appears (with timeout)
4. Container reads the result and deletes the file

---

## Session Lifecycle

### First message (new session)

```
1. First message to group
2. Container spawns with sessionId = undefined
3. SDK creates new session, returns UUID via system/init message
4. agent-runner captures newSessionId
5. Host receives newSessionId in ContainerOutput
6. SessionManager.set(groupFolder, newSessionId) writes to sessions table
```

### Ongoing messages (active session)

```
1. Message arrives for group
2. Host reads sessionId from SessionManager.get(groupFolder)
3. Container spawns with resume: sessionId
4. SDK loads .jsonl transcript, agent has full context
5. If follow-up messages arrive, they pipe to /workspace/ipc/input/ (MessageStream)
6. resumeAt tracks last assistant UUID for multi-query continuity
```

### Clear session

```
1. Agent calls clear_session MCP tool with a friendly name
2. MCP tool writes IPC file to /workspace/ipc/tasks/
3. Host ClearSessionHandler:
   a. Reads current sessionId from SessionManager
   b. Reads .jsonl transcript, formats as markdown
   c. Inserts into conversation_archives (sessionId + name + content)
   d. Deletes sessionId from sessions table
   e. Writes _close sentinel to stop the container
4. Next message spawns container with sessionId = undefined → new session
5. Old .jsonl remains on disk in .claude/projects/
```

### List sessions

```
1. Host writes conversation_archives snapshot to session_history.json before spawning container
2. Agent calls list_sessions → reads session_history.json snapshot
3. Returns list of archived conversations with IDs and names
```

### Search sessions

```
1. Agent calls search_sessions with keyword(s)
2. MCP tool writes IPC request to tasks/ with requestId
3. Host SearchSessionsHandler queries conversation_archives WHERE content LIKE '%query%'
4. Host writes result to responses/{requestId}.json
5. MCP tool polls and reads the response file
6. Returns matching conversations
```

### Resume session

```
1. Agent calls list_sessions → reads session_history.json snapshot
2. Agent calls resume_session with archive ID
3. Host ResumeSessionHandler:
   a. Looks up target in conversation_archives by ID → gets session_id
   b. Archives current session to conversation_archives (if save name provided)
   c. Sets target session_id as active in sessions table
   d. Deletes the target from conversation_archives (it's now active)
   e. Writes _close sentinel to stop the container
4. Next message spawns container with resume: restored sessionId
5. SDK loads the old .jsonl → agent has that conversation's context
```

### PreCompact (SDK compaction)

```
1. SDK determines conversation is too long, triggers PreCompact hook
2. PreCompact hook in agent-runner:
   a. Reads full transcript from transcript_path
   b. Parses and formats as markdown
   c. Writes IPC file to tasks/ with type: archive_session
3. Host ArchiveSessionHandler inserts into conversation_archives
4. SDK compacts the transcript (summarizes old messages)
5. Full pre-compaction content is preserved in the archive
```

### Scheduled tasks

```
1. Task scheduler spawns container for the group
2. If context_mode is "group": container gets the group's active sessionId
3. If context_mode is "isolated": container gets sessionId = undefined (fresh)
4. Task executes, session management works the same as regular messages
```

---

## Per-Group Isolation

Each group's memory is fully isolated:

| Resource | Isolation |
|---|---|
| SDK state | `data/sessions/{group}/.claude/` — separate directory per group |
| Session pointers | `sessions` table keyed by `group_folder` |
| Conversation archives | `conversation_archives` table filtered by `group_folder` |
| IPC snapshots | `data/ipc/{group}/session_history.json` — per-group |

Non-main groups cannot access other groups' sessions, archives, or history. Main group has access to the full project filesystem including all group directories.

### Global memory

`groups/global/CLAUDE.md` is a shared read-only file mounted at `/workspace/global/CLAUDE.md` for non-main groups. Its content is appended to the system prompt via the `append` parameter:

```python
system_prompt={"type": "preset", "preset": "claude_code", "append": global_claude_md}
if global_claude_md else None
```

Main group doesn't need this mount since it has direct access to the entire project tree.

---

## Key Files

| File | Layer | Purpose |
|---|---|---|
| `src/g2/sessions/manager.py` | 2 | In-memory + SQLite session pointer management |
| `src/g2/sessions/repository.py` | 2 | SQLite accessors for sessions/archives |
| `src/g2/ipc/handlers/session_handlers.py` | 2 | IPC handlers for clear/resume/search/archive session |
| `src/g2/execution/mount_builder.py` | 1 | Mount `.claude/` directory, init settings, sync skills |
| `src/g2/execution/container_runner.py` | 1, 2 | Write session history snapshot, capture newSessionId |
| `container/agent-runner/src/main.py` | 1 | SDK query with resume, PreCompact hook (writes IPC) |
| `container/agent-runner/src/ipc_mcp_stdio.py` | — | MCP tools: clear/list/resume/search session |
| `groups/{group}/CLAUDE.md` | — | Per-group instructions (references search_sessions) |
| `groups/global/CLAUDE.md` | — | Global instructions appended to system prompt |
