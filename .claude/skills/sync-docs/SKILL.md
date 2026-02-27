---
name: sync-docs
description: Synchronize documentation with actual codebase structure after refactoring. Scans source files, cross-references all doc files, and fixes stale paths, missing files, outdated descriptions, and inaccurate language.
---

# Sync Documentation After Refactoring

Run this skill after any major refactoring to ensure all documentation reflects the actual codebase.

## Step 1: Scan the Actual Codebase

Build a map of every source file and what it contains.

### Source files

```bash
# All non-test Python files in src/g2/ (the authoritative file list)
find src/g2 -name '*.py' ! -name '*test*' ! -path '*__pycache__*' | sort
```

For each file, note:
- Exported classes, functions, constants (read the file)
- Which directory it's in (`src/g2/`, `src/g2/infrastructure/`, `src/g2/messaging/`, `src/g2/execution/`, `src/g2/sessions/`, `src/g2/scheduling/`, `src/g2/groups/`, `src/g2/ipc/`, etc.)

### Container files

```bash
find container -name '*.py' -o -name '*.md' -o -name 'Dockerfile' -o -name '*.sh' | sort
```

### Group structure

```bash
ls -la groups/
ls groups/*/CLAUDE.md 2>/dev/null
```

## Step 2: Read All Documentation Files

Read every documentation file that references codebase structure:

| File | What to check |
|------|--------------|
| `CLAUDE.md` | Key Files tables — every non-test `src/g2/` file should appear |
| `README.md` | Architecture "Key files" list, philosophy language |
| `docs/ARCHITECTURE.md` | Layer descriptions, mount tables, IPC commands, SQLite tables, startup sequence — must match actual source |
| `docs/CHANNEL-MANAGEMENT.md` | Channel Protocol, registry, JID routing, WhatsApp implementation, message queue, metadata sync, inbound/outbound flow, database schema — must match `src/g2/messaging/types.py`, `src/g2/messaging/channel_registry.py`, `src/g2/messaging/whatsapp/channel.py`, `src/g2/messaging/whatsapp/outgoing_queue.py`, `src/g2/messaging/whatsapp/metadata_sync.py`, `src/g2/messaging/formatter.py`, `src/g2/groups/authorization.py`, `src/g2/infrastructure/database.py`, `src/g2/infrastructure/config.py`, `src/g2/app.py` |
| `docs/HEARTBEAT.md` | Polling loop intervals, timing constants, scheduler flow, ExecutionQueue behavior, idle timer, IPC watcher mechanism — must match `src/g2/infrastructure/config.py`, `src/g2/scheduling/scheduler.py`, `src/g2/ipc/watcher.py`, `src/g2/execution/execution_queue.py`, `src/g2/infrastructure/poll_loop.py`, `src/g2/infrastructure/idle_timer.py`, `src/g2/ipc/transport.py`, `src/g2/scheduling/snapshot_writer.py` |
| `docs/MEMORY.md` | Session management flow, archive/restore lifecycle, IPC handlers for sessions, DB schema — must match `src/g2/sessions/manager.py`, `src/g2/infrastructure/database.py`, `src/g2/ipc/handlers/session_handlers.py` |
| `docs/SPEC.md` | Folder Structure tree — must mirror actual `src/g2/` layout |
| `docs/REQUIREMENTS.md` | Design Patterns section — must name actual classes, protocols, modules |

Also read these for any stale `src/` file references (they usually don't have them, but check):
- `docs/SECURITY.md`
- `docs/DEBUG_CHECKLIST.md`

## Step 3: Cross-Reference and Identify Issues

For each documentation file, check for these categories of staleness:

### 3a. Missing files (source file exists but not documented)

Compare the `find src/g2` output against what's listed in:
- `CLAUDE.md` Key Files tables
- `docs/ARCHITECTURE.md` layer descriptions
- `docs/SPEC.md` Folder Structure tree

Also check domain-specific docs reference the correct source files:
- `docs/HEARTBEAT.md` — polling loop, scheduler, queue, IPC, and utility files
- `docs/MEMORY.md` — session manager, session handlers, DB functions
- `docs/CHANNEL-MANAGEMENT.md` — channel Protocol, registry, WhatsApp channel, message queue, metadata sync, message formatter, authorization, DB schema

Every non-test `.py` file in `src/g2/` should appear in both. If a file is missing from the docs, add it with an accurate description based on reading its exports.

### 3b. Ghost references (doc mentions a file that doesn't exist)

For every `src/` path mentioned in any doc file, verify the file actually exists. Remove or update references to deleted/renamed files. Watch especially for stale `.ts` references from the Node.js version — these should all be `.py` paths now.

### 3c. Stale descriptions

For files that exist in both the codebase and docs, verify the description is still accurate. Read the file's exports and compare against the documented purpose. Update if the file's role has changed.

### 3d. Missing directories

If new directories were added under `src/g2/` (e.g., `src/g2/infrastructure/`, `src/g2/messaging/`, `src/g2/execution/`, `src/g2/sessions/`, `src/g2/scheduling/`, `src/g2/groups/`, `src/g2/ipc/`), they need:
- A section in `CLAUDE.md` Key Files
- Coverage in the appropriate layer in `docs/ARCHITECTURE.md`
- A directory entry in `docs/SPEC.md` Folder Structure
- Mention in `docs/REQUIREMENTS.md` Design Patterns if they represent a pattern

### 3e. Stale language

Check for phrases that may no longer be accurate after refactoring:
- "handful of files", "a few source files", "minimal glue code" — may understate a now-modular codebase
- "no abstraction layers" — inaccurate if protocols/interfaces exist
- Any count of files that's now wrong
- TypeScript/Node.js references that should now be Python (e.g., "TypeScript interfaces" → "Python Protocols", "npm run build" → no build step, etc.)

Grep for these patterns:
```bash
grep -rn 'handful\|few source\|few files\|minimal glue\|no abstraction\|\.ts\b\|npm run\|node_modules\|TypeScript' CLAUDE.md README.md docs/ARCHITECTURE.md docs/REQUIREMENTS.md docs/SPEC.md
```

### 3f. Container skill paths

Verify `container/skills/` paths in docs match actual structure:
```bash
find container/skills -type f | sort
```

## Step 4: Apply Fixes

For each issue found, make the edit directly. Follow these rules:

- **CLAUDE.md**: Organize Key Files into categorized tables by directory (Core, Infrastructure, Messaging, Execution, Sessions, Scheduling, Groups, IPC, Other). Every non-test source file gets a row.
- **README.md**: The Architecture "Key files" list should be a curated summary (not exhaustive) — list the most important files plus directory-level entries for bounded-context directories (`src/g2/infrastructure/`, `src/g2/messaging/`, `src/g2/execution/`, `src/g2/sessions/`, `src/g2/scheduling/`, `src/g2/groups/`, `src/g2/ipc/`).
- **docs/ARCHITECTURE.md**: Layer descriptions must reference actual source files. Mount tables must match `DefaultMountFactory` logic. IPC command table must match handlers in `src/g2/ipc/handlers/`. SQLite table list must match `src/g2/infrastructure/database.py` schema. Authorization matrix must match `src/g2/groups/authorization.py`. Startup sequence must match `Orchestrator` in `src/g2/app.py`. Config values (intervals, timeouts, concurrency limits) must match `src/g2/infrastructure/config.py`.
- **docs/SPEC.md**: The Folder Structure tree must show every file and directory exactly as they exist on disk.
- **docs/HEARTBEAT.md**: Polling intervals must match `src/g2/infrastructure/config.py` constants. Scheduler flow must match `src/g2/scheduling/scheduler.py`. IPC watcher mechanism must match `src/g2/ipc/watcher.py` (watchfiles vs polling, fallback interval). ExecutionQueue behavior must match `src/g2/execution/execution_queue.py`. Idle timer description must match `src/g2/infrastructure/idle_timer.py`. Task snapshot helper must match `src/g2/scheduling/snapshot_writer.py`.
- **docs/CHANNEL-MANAGEMENT.md**: Channel Protocol must match `src/g2/messaging/types.py` (`Channel`, `OnInboundMessage`, `OnChatMetadata`). Registry methods must match `src/g2/messaging/channel_registry.py`. WhatsApp implementation details (connection, reconnection, LID translation, bot detection, typing) must match `src/g2/messaging/whatsapp/channel.py`. Outgoing queue behavior must match `src/g2/messaging/whatsapp/outgoing_queue.py`. Metadata sync timing and cache logic must match `src/g2/messaging/whatsapp/metadata_sync.py`. Outbound formatting must match `src/g2/messaging/formatter.py`. Authorization matrix must match `src/g2/groups/authorization.py`. Database schema must match `src/g2/infrastructure/database.py`. Config constants must match `src/g2/infrastructure/config.py`. Initialization and shutdown sequence must match `src/g2/app.py`.
- **docs/MEMORY.md**: Session management flow must match `src/g2/sessions/manager.py`. DB tables must match `src/g2/infrastructure/database.py` schema. Archive/restore lifecycle must match IPC handlers in `src/g2/ipc/handlers/session_handlers.py`. Container-side behavior must match `container/agent-runner/src/main.py`.
- **docs/REQUIREMENTS.md**: The Design Patterns section should name actual classes/protocols/functions. Architecture Decisions subsections should reference the modules that implement them.
- **Language fixes**: Replace stale phrases with accurate ones. Don't overstate or understate the codebase size. Replace TypeScript terminology with Python equivalents (interfaces → Protocols, etc.).

## Step 5: Verify

After all edits, do a final sanity check:

```bash
# Every src/ file path mentioned in docs should exist
grep -Eoh 'src/g2/[a-zA-Z0-9_/.-]+\.py' CLAUDE.md README.md docs/ARCHITECTURE.md docs/CHANNEL-MANAGEMENT.md docs/HEARTBEAT.md docs/MEMORY.md docs/SPEC.md docs/REQUIREMENTS.md | sort -u | while read f; do
  [ -f "$f" ] || echo "BROKEN REF: $f"
done

# Every container/ path mentioned in docs should exist
grep -Eoh 'container/[a-zA-Z0-9_/.-]+\.[a-z]+' CLAUDE.md README.md docs/ARCHITECTURE.md docs/CHANNEL-MANAGEMENT.md docs/HEARTBEAT.md docs/MEMORY.md docs/SPEC.md docs/REQUIREMENTS.md | sort -u | while read f; do
  [ -f "$f" ] || echo "BROKEN REF: $f"
done

# Check for stale TypeScript references
grep -rn '\.ts\b' CLAUDE.md README.md docs/ARCHITECTURE.md docs/CHANNEL-MANAGEMENT.md docs/HEARTBEAT.md docs/MEMORY.md docs/SPEC.md docs/REQUIREMENTS.md | grep -v '\.tsx\?' || echo "No stale .ts references"
```

If any broken refs remain, fix them.

## What This Skill Does NOT Do

- Does not update `groups/*/CLAUDE.md` (those are per-group agent memory, not project docs)
- Does not update `docs/SDK_DEEP_DIVE.md` (SDK reference, not codebase structure)
- Does not modify source code — only documentation files

**Note:** `docs/ARCHITECTURE.md`, `docs/CHANNEL-MANAGEMENT.md`, `docs/HEARTBEAT.md`, and `docs/MEMORY.md` ARE in scope — they document the runtime system architecture and must stay in sync with the source code.
