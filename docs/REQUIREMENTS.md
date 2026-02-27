# G2 Requirements

Original requirements and design decisions from the project creator.

---

## Why This Exists

This is a lightweight, secure alternative to OpenClaw (formerly ClawBot). That project became a monstrosity - 4-5 different processes running different gateways, endless configuration files, endless integrations. It's a security nightmare where agents don't run in isolated processes; there's all kinds of leaky workarounds trying to prevent them from accessing parts of the system they shouldn't. It's impossible for anyone to realistically understand the whole codebase. When you run it you're kind of just yoloing it.

G2 gives you the core functionality without that mess.

---

## Philosophy

### Small Enough to Understand

The entire codebase should be something you can read and understand. One Python process. Composable modules with clean interfaces. No microservices, no message queues.

### Security Through True Isolation

Instead of application-level permission systems trying to prevent agents from accessing things, agents run in actual Linux containers. The isolation is at the OS level. Agents can only see what's explicitly mounted. Bash access is safe because commands run inside the container, not on your Mac.

### Built for One User

This isn't a framework or a platform. It's working software for my specific needs. I use WhatsApp and Email, so it supports WhatsApp and Email. I don't use Telegram, so it doesn't support Telegram. I add the integrations I actually want, not every possible integration.

### Customization = Code Changes

No configuration sprawl. If you want different behavior, modify the code. The codebase is small enough that this is safe and practical. Very minimal things like the trigger word are in config. Everything else - just change the code to do what you want.

### AI-Native Development

I don't need an installation wizard - Claude Code guides the setup. I don't need a monitoring dashboard - I ask Claude Code what's happening. I don't need elaborate logging UIs - I ask Claude to read the logs. I don't need debugging tools - I describe the problem and Claude fixes it.

The codebase assumes you have an AI collaborator. It doesn't need to be excessively self-documenting or self-debugging because Claude is always there.

### Skills Over Features

When people contribute, they shouldn't add "Telegram support alongside WhatsApp." They should contribute a skill like `/add-telegram` that transforms the codebase. Users fork the repo, run skills to customize, and end up with clean code that does exactly what they need - not a bloated system trying to support everyone's use case simultaneously.

---

## RFS (Request for Skills)

Skills we'd love contributors to build:

### Communication Channels
Skills to add or switch to different messaging platforms:
- `/add-telegram` - Add Telegram as an input channel
- `/add-slack` - Add Slack as an input channel
- `/add-discord` - Add Discord as an input channel
- `/add-sms` - Add SMS via Twilio or similar
- `/convert-to-telegram` - Replace WhatsApp with Telegram entirely

### Container Runtime
The project uses Docker by default (cross-platform). For macOS users who prefer Apple Container:
- `/convert-to-apple-container` - Switch from Docker to Apple Container (macOS-only)

### Platform Support
- `/setup-linux` - Make the full setup work on Linux (depends on Docker conversion)
- `/setup-windows` - Windows support via WSL2 + Docker

---

## Vision

A personal Claude assistant accessible via WhatsApp, with minimal custom code.

**Core components:**
- **Claude Agent SDK** as the core agent
- **Containers** for isolated agent execution (Linux VMs)
- **WhatsApp** as the primary I/O channel
- **Persistent memory** per conversation and globally
- **Scheduled tasks** that run Claude and can message back
- **Web access** for search and browsing
- **Browser automation** via agent-browser

**Implementation approach:**
- Use existing tools (WhatsApp connector, Claude Agent SDK, MCP servers)
- Composable, interface-driven modules with dependency injection for testability
- File-based systems where possible (CLAUDE.md for memory, folders for groups)

---

## Architecture Decisions

### Design Patterns

The codebase uses composable, interface-driven design:

- **Interface abstractions** — Core behaviors are defined as Protocols (`ContainerRuntime`, `MountFactory`), decoupling consumers from implementations. Swapping Docker for Apple Container means providing a different `ContainerRuntime`.
- **Dependency injection** — Modules accept their dependencies as constructor/function parameters with sensible defaults. `ContainerRunner` accepts optional `runtime` and `mount_factory`, making it testable with mocks and swappable at runtime.
- **Registry pattern** — `ChannelRegistry` manages multiple communication channels. Channels implement the `Channel` interface and register themselves; the orchestrator routes messages by asking the registry which channel owns a given JID.
- **Command dispatcher** — IPC commands from containers are handled by an `IpcDispatcher` that routes to modular `IpcCommandHandler` implementations organized in consolidated handler files (`src/g2/ipc/handlers/`). Adding a new IPC command means adding a handler to the appropriate domain handler file.
- **Manager classes** — `SessionManager` encapsulates Claude Agent SDK session state with an in-memory cache backed by SQLite persistence.
- **Repository pattern** — Database operations are split into domain-specific repository classes co-located with their domain modules (e.g., `src/g2/messaging/repository.py`, `src/g2/scheduling/repository.py`, `src/g2/sessions/repository.py`, `src/g2/groups/repository.py`, `src/g2/infrastructure/state_repo.py`).
- **Composed services** — The `App` composes `MessagePoller` (message polling, cursor management, trigger checking) and `AgentExecutor` (container execution, session tracking, snapshot writing) rather than implementing all logic inline. Each service owns its specific state and concerns.
- **Authorization as a policy class** — `authorization.py` exports an `AuthorizationPolicy` class that encapsulates checks for a single `AuthContext` (`canSendMessage`, `canScheduleTask`, `canRegisterGroup`, etc.). No side effects, trivially testable.
- **Single responsibility modules** — Each concern has its own module: mount security (`MountSecurity`), timeout configuration (`TimeoutConfig` in `Config`), outbound message rate limiting (`OutgoingMessageQueue`), message formatting (`MessageFormatter`), path construction (`GroupPaths`).

### Message Routing
- Channels implement the `Channel` interface and register with `ChannelRegistry`
- Only messages from registered groups are processed
- Trigger matching is handled by `MessagePoller` — `@G2` prefix (case insensitive), configurable via `ASSISTANT_NAME` env var
- Unregistered groups are ignored completely

### Memory System
- **Per-group memory**: Each group has a folder with its own `CLAUDE.md`
- **Global memory**: Root `CLAUDE.md` is read by all groups, but only writable from "main" (self-chat)
- **Files**: Groups can create/read files in their folder and reference them
- Agent runs in the group's folder, automatically inherits both CLAUDE.md files

### Session Management
- Each group maintains a conversation session (via Claude Agent SDK)
- `SessionManager` provides an in-memory cache with SQLite persistence, plus archive/restore for session history
- Sessions auto-compact when context gets too long, preserving critical information

### Container Isolation
- All agents run inside containers (lightweight Linux VMs)
- Container runtime is abstracted behind `ContainerRuntime`; Docker is the default, Apple Container available via `/convert-to-apple-container`
- Mount construction is abstracted behind `MountFactory`; `MountBuilder` builds mounts based on group identity and main/non-main status
- Mount security is enforced by `MountSecurity` with an external allowlist at `~/.config/g2/mount-allowlist.json`
- Containers provide filesystem isolation - agents can only see mounted paths
- Bash access is safe because commands run inside the container, not on the host
- Browser automation via agent-browser with Chromium in the container

### IPC & Scheduled Tasks
- IPC commands from containers are dispatched by `IpcDispatcher` to modular handlers
- Users can ask Claude to schedule recurring or one-time tasks from any group
- Tasks run as full agents in the context of the group that created them
- Tasks have access to all tools including Bash (safe in container)
- Tasks can optionally send messages to their group via `send_message` tool, or complete silently
- Task runs are logged to the database with duration and result
- Schedule types: cron expressions, intervals (ms), or one-time (ISO timestamp)
- Authorization is enforced per-operation: main can schedule/manage tasks for any group; non-main groups can only manage their own

### Group Management
- New groups are added explicitly via the main channel
- Groups are registered in SQLite (via the main channel or IPC `register_group` command)
- Each group gets a dedicated folder under `groups/`
- Groups can have additional directories mounted via `containerConfig`

### Authorization
- Fine-grained, per-operation authorization via pure functions in `src/g2/groups/authorization.py`
- Each IPC operation checks auth before executing: `canSendMessage`, `canScheduleTask`, `canManageTask`, `canRegisterGroup`, `canRefreshGroups`, `canManageSession`
- Main channel is the admin/control group (typically self-chat) — has full privileges
- Non-main groups are restricted to their own resources

---

## Integration Points

### WhatsApp
- Using baileys library for WhatsApp Web connection
- Messages stored in SQLite, polled by router
- QR code authentication during setup

### Scheduler
- Built-in scheduler runs on the host, spawns containers for task execution
- Custom `g2` MCP server (inside container) provides scheduling tools
- Tools: `schedule_task`, `list_tasks`, `pause_task`, `resume_task`, `cancel_task`, `send_message`
- Tasks stored in SQLite with run history
- Scheduler loop checks for due tasks every minute
- Tasks execute Claude Agent SDK in containerized group context

### Web Access
- Built-in WebSearch and WebFetch tools
- Standard Claude Agent SDK capabilities

### Browser Automation
- agent-browser CLI with Chromium in container
- Snapshot-based interaction with element references (@e1, @e2, etc.)
- Screenshots, PDFs, video recording
- Authentication state persistence

---

## Setup & Customization

### Philosophy
- Minimal configuration files
- Setup and customization done via Claude Code
- Users clone the repo and run Claude Code to configure
- Each user gets a custom setup matching their exact needs

### Skills
- `/setup` - Install dependencies, authenticate WhatsApp, configure scheduler, start services
- `/customize` - General-purpose skill for adding capabilities (new channels like Telegram, new integrations, behavior changes)

### Deployment
- Runs on local Mac via launchd
- Single Python process handles everything

---

## Personal Configuration (Reference)

These are the creator's settings, stored here for reference:

- **Trigger**: `@G2` (case insensitive)
- **Response prefix**: `G2:`
- **Persona**: Default Claude (no custom personality)
- **Main channel**: Self-chat (messaging yourself in WhatsApp)

---

## Project Name

**G2** - A reference to Clawdbot (now OpenClaw).
