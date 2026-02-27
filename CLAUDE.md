# G2

Personal Claude assistant. See [README.md](README.md) for philosophy and setup. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for system architecture. See [docs/CHANNEL-MANAGEMENT.md](docs/CHANNEL-MANAGEMENT.md) for channel architecture. See [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) for architecture decisions. See [docs/HEARTBEAT.md](docs/HEARTBEAT.md) for the polling loops and task scheduler.

## Quick Context

Single Python process that connects to WhatsApp, routes messages to Claude Agent SDK running in containers (Linux VMs). Each group has isolated filesystem and memory.

## Key Files

### Core
| File | Purpose |
|------|---------|
| `src/g2/__main__.py` | Entry point: `python -m g2` bootstrap |
| `src/g2/app.py` | Orchestrator class: composes services, wires subsystems |
| `src/g2/types.py` | Barrel re-export of all domain types |

### Infrastructure (`src/g2/infrastructure/`)
| File | Purpose |
|------|---------|
| `src/g2/infrastructure/config.py` | Trigger pattern, paths, intervals, container settings, `TimeoutConfig`, `.env` parsing |
| `src/g2/infrastructure/database.py` | Schema creation, migrations, `AppDatabase` composition root |
| `src/g2/infrastructure/logger.py` | structlog logger singleton |
| `src/g2/infrastructure/state_repo.py` | Router state (key-value) persistence |
| `src/g2/infrastructure/poll_loop.py` | Shared polling loop abstraction |
| `src/g2/infrastructure/idle_timer.py` | Shared idle timer utility |

### Messaging (`src/g2/messaging/`)
| File | Purpose |
|------|---------|
| `src/g2/messaging/types.py` | `Channel` Protocol, `OnInboundMessage`, `OnChatMetadata`, `NewMessage` |
| `src/g2/messaging/poller.py` | Message polling, cursor management, trigger checking |
| `src/g2/messaging/formatter.py` | Message format transforms (XML encoding, internal tag stripping) |
| `src/g2/messaging/repository.py` | Message + chat metadata storage and retrieval |
| `src/g2/messaging/channel_registry.py` | Registry pattern for multiple channels |
| `src/g2/messaging/whatsapp/channel.py` | WhatsApp connection, auth, send/receive (neonize) |
| `src/g2/messaging/whatsapp/metadata_sync.py` | WhatsApp group metadata syncing |
| `src/g2/messaging/whatsapp/outgoing_queue.py` | Rate-limited outbound message queue |
| `src/g2/messaging/gmail/channel.py` | Gmail channel (google-api-python-client) |

### Execution (`src/g2/execution/`)
| File | Purpose |
|------|---------|
| `src/g2/execution/agent_executor.py` | Container execution, session tracking, snapshot writing |
| `src/g2/execution/container_runner.py` | `ContainerRunner`: spawns agent containers, parses output |
| `src/g2/execution/output_parser.py` | Stateful parser for OUTPUT_START/END marker protocol |
| `src/g2/execution/container_runtime.py` | `ContainerRuntime` Protocol + `DockerRuntime` implementation |
| `src/g2/execution/execution_queue.py` | Per-group queue with global concurrency limit |
| `src/g2/execution/mount_builder.py` | `MountFactory` Protocol + `DefaultMountFactory` implementation |
| `src/g2/execution/mount_security.py` | Mount allowlist validation for containers |

### Sessions (`src/g2/sessions/`)
| File | Purpose |
|------|---------|
| `src/g2/sessions/types.py` | `ArchivedSession` |
| `src/g2/sessions/manager.py` | Session + archive lifecycle (clear, resume, search), transcript formatting |
| `src/g2/sessions/repository.py` | Session + conversation archive persistence |

### Scheduling (`src/g2/scheduling/`)
| File | Purpose |
|------|---------|
| `src/g2/scheduling/types.py` | `ScheduledTask`, `TaskRunLog` |
| `src/g2/scheduling/task_service.py` | `TaskManager`: centralized task lifecycle (create, pause, resume, cancel) |
| `src/g2/scheduling/scheduler.py` | Runs scheduled tasks via `TaskManager` |
| `src/g2/scheduling/repository.py` | Scheduled task CRUD, claiming, run logging |
| `src/g2/scheduling/snapshot_writer.py` | Writes tasks, sessions, groups snapshots for containers |

### Groups (`src/g2/groups/`)
| File | Purpose |
|------|---------|
| `src/g2/groups/types.py` | `RegisteredGroup`, `ContainerConfig`, `AdditionalMount`, `MountAllowlist`, `AllowedRoot` |
| `src/g2/groups/authorization.py` | Fine-grained auth (`AuthorizationPolicy` class) |
| `src/g2/groups/paths.py` | Centralized path construction for group directories |
| `src/g2/groups/repository.py` | Registered group persistence |

### IPC (`src/g2/ipc/`)
| File | Purpose |
|------|---------|
| `src/g2/ipc/dispatcher.py` | `IpcCommandDispatcher` + `IpcCommandHandler` base class |
| `src/g2/ipc/watcher.py` | `IpcWatcher`: watchfiles + fallback poll, dispatches IPC commands |
| `src/g2/ipc/transport.py` | File-based IPC write operations |
| `src/g2/ipc/handlers/task_handlers.py` | `schedule_task`, `pause_task`, `resume_task`, `cancel_task` handlers |
| `src/g2/ipc/handlers/session_handlers.py` | `clear_session`, `resume_session`, `search_sessions`, `archive_session` handlers |
| `src/g2/ipc/handlers/group_handlers.py` | `register_group`, `refresh_groups` handlers |

### Other
| File | Purpose |
|------|---------|
| `groups/{name}/CLAUDE.md` | Per-group memory (isolated) |
| `container/agent-runner/src/main.py` | Python agent runner inside Docker containers |
| `container/skills/agent-browser/SKILL.md` | Browser automation skill (available to all agents) |

## Skills

| Skill | When to Use |
|-------|-------------|
| `/setup` | First-time installation, authentication, service configuration |
| `/customize` | Adding channels, integrations, changing behavior |
| `/debug` | Container issues, logs, troubleshooting |
| `/restart` | Restart G2 service, verify health, optionally rebuild container |
| `/sync-docs` | After major refactoring — sync all docs with actual codebase structure |

## Development

Run commands directly—don't tell the user to run them.

```bash
# Using uv (recommended)
uv run python -m g2           # Run the application
uv run pytest                  # Run tests
uv run ruff check src/ tests/  # Lint
uv run ruff format src/ tests/ # Format
uv run mypy src/g2/            # Type check

# Using pip/venv
python -m g2                   # Run the application
pytest                         # Run tests
ruff check src/ tests/         # Lint
ruff format src/ tests/        # Format

./container/build.sh           # Rebuild agent container
```

Service management:
```bash
# systemd (Linux)
sudo systemctl start g2
sudo systemctl stop g2

# launchctl (macOS)
launchctl load ~/Library/LaunchAgents/com.g2.plist
launchctl unload ~/Library/LaunchAgents/com.g2.plist
```

## Container Build Cache

The container buildkit caches the build context aggressively. `--no-cache` alone does NOT invalidate COPY steps — the builder's volume retains stale files. To force a truly clean rebuild, prune the builder then re-run `./container/build.sh`.
