<p align="center">
  <img src="https://raw.githubusercontent.com/v-gaurav/G2/main/assets/g2-logo.svg" alt="G2" width="400">
</p>

<p align="center">
  Totally reimagined Enterpise Grade Personal AI assistant. Inspired by <a href="https://github.com/qwibitai/nanoclaw">NanoClaw</a>.
</p>

<p align="center">
  <a href="https://github.com/v-gaurav/g2/tree/main/repo-tokens"><img src="https://raw.githubusercontent.com/v-gaurav/G2/main/repo-tokens/badge.svg" alt="repo tokens"></a>
  <!-- token-count --><br><a href="https://github.com/v-gaurav/g2/tree/main/repo-tokens">28% of context window</a><!-- /token-count -->
</p>

---

## Table of Contents

- [Why G2](#why-g2)
- [Features](#features)
- [Quick Start](#quick-start)
- [Requirements](#requirements)
- [Usage](#usage)
- [Architecture](#architecture)
- [Configuration](#configuration)
- [Memory System](#memory-system)
- [Scheduled Tasks](#scheduled-tasks)
- [Security](#security)
- [Customizing](#customizing)
- [Skills](#skills)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [FAQ](#faq)
- [Documentation](#documentation)
- [License](#license)

---

## Why G2

G2 is my personal fork of [NanoClaw](https://github.com/qwibitai/nanoclaw). Same philosophy — a personal Claude assistant you can actually understand — but tailored to my exact needs.

One process. Composable modules with clean interfaces. Agents run in actual Linux containers with filesystem isolation, not behind permission checks.

## Features

- **WhatsApp I/O** — Message Claude from your phone
- **Multi-channel support** — WhatsApp built-in, Telegram and Discord via skills
- **Isolated group context** — Each group has its own `CLAUDE.md` memory, isolated filesystem, and runs in its own container sandbox
- **Main channel** — Your private channel (self-chat) for admin control; every other group is completely isolated
- **Persistent memory** — Hierarchical CLAUDE.md files: global, per-group, and arbitrary notes that survive session clears
- **Session continuity** — Claude remembers conversation history via JSONL transcripts and the Agent SDK's resume mechanism
- **Scheduled tasks** — Recurring or one-time jobs (cron, interval, timestamp) that run Claude as a full agent and can message you back
- **Web access** — Search and fetch content from the internet
- **Browser automation** — agent-browser with Chromium for screenshots, PDFs, and web interaction
- **Container isolation** — Agents sandboxed in Apple Container (macOS) or Docker (macOS/Linux)
- **Agent Swarms** — Spin up teams of specialized agents that collaborate on complex tasks
- **Optional integrations** — Add Gmail (`/add-gmail`), voice transcription (`/add-voice-transcription`), X/Twitter (`/x-integration`) and more via skills

## Quick Start

```bash
git clone git@github.com:v-gaurav/G2.git
cd G2
claude
```

Then run `/setup`. Claude Code handles everything: dependencies, authentication, container setup, service configuration.

### Manual Setup

If you prefer step-by-step:

1. `uv sync` (or `pip install -e .`)
2. Copy `.env.example` to `.env` and add Claude credentials
3. `./container/build.sh` to build the agent container image
4. `uv run python -m g2` (or `python -m g2`)
5. Scan the QR code with WhatsApp to link the device
6. Send yourself a message: `@G2 hello` to register the main channel

## Requirements

- macOS or Linux
- Python 3.12+
- [Claude Code](https://claude.ai/download)
- [Apple Container](https://github.com/apple/container) (macOS) or [Docker](https://docker.com/products/docker-desktop) (macOS/Linux)
- A WhatsApp account
- Claude authentication (OAuth token from `~/.claude/.credentials.json` or an `ANTHROPIC_API_KEY`)

## Usage

Talk to your assistant with the trigger word (default: `@G2`):

```
@G2 what's the weather in Tokyo?
@G2 send an overview of the sales pipeline every weekday morning at 9am
@G2 review the git history for the past week each Friday and update the README if there's drift
@G2 every Monday at 8am, compile news on AI developments from Hacker News and TechCrunch and message me a briefing
```

From the main channel (your self-chat), manage groups and tasks:

```
@G2 join the Family Chat group
@G2 list all scheduled tasks across groups
@G2 pause the Monday briefing task
@G2 remember I prefer concise responses
```

### Trigger Matching

- `@G2 help me` — triggers (case insensitive)
- `Hey @G2` — ignored (trigger must be at the start)
- `What's up?` — ignored (no trigger)

When `ASSISTANT_HAS_OWN_NUMBER=true`, every message in registered groups triggers the agent without needing the @mention, and DMs serve as the main channel.

### Conversation Catch-Up

When a triggered message arrives, the agent receives all messages since its last interaction in that chat, formatted with timestamp and sender:

```
[Jan 31 2:32 PM] John: hey everyone, should we do pizza tonight?
[Jan 31 2:33 PM] Sarah: sounds good to me
[Jan 31 2:35 PM] John: @G2 what toppings do you recommend?
```

## Architecture

```
Channel (WhatsApp/TG/DC) --> SQLite --> Polling loop --> Container (Claude Agent SDK) --> Response
```

Single Python process. Agents execute in isolated Linux containers with mounted directories. Per-group message queue with concurrency control. IPC via filesystem.

### How It Works

1. Messages arrive via WhatsApp (or Telegram/Discord) and are stored in SQLite
2. A polling loop (every 2s) checks for new messages matching the trigger pattern
3. The router catches up the full conversation since the last agent interaction
4. A container is spawned with the group's directory, memory, and session mounted
5. Claude Agent SDK runs inside the container with full tool access (Bash, file ops, web, browser)
6. The response is extracted via `OUTPUT_START`/`OUTPUT_END` markers, prefixed with the assistant name, and sent back
7. Session ID is saved for conversation continuity

### Technology Stack

| Component | Technology |
|-----------|------------|
| WhatsApp | neonize |
| Database | SQLite (aiosqlite) |
| Containers | Docker or Apple Container |
| Agent | anthropic-ai/claude-agent-sdk |
| Browser | agent-browser + Chromium |
| IPC | File-based JSON |
| Logging | structlog |
| Runtime | Python 3.12+ |

### Key Files

| File | Purpose |
|------|---------|
| `src/g2/__main__.py` | Entry point: `python -m g2` bootstrap |
| `src/g2/app.py` | Composition root: wires all services |
| `src/g2/messaging/poller.py` | Message polling, cursor management, trigger checking |
| `src/g2/execution/agent_executor.py` | Container execution, session tracking |
| `src/g2/execution/container_runner.py` | Spawns agent containers |
| `src/g2/execution/execution_queue.py` | Per-group queue with global concurrency limit |
| `src/g2/messaging/channel_registry.py` | Multi-channel registry with prefix routing |
| `src/g2/scheduling/scheduler.py` | Runs scheduled tasks when due |
| `src/g2/sessions/manager.py` | Session resume and archive management |
| `src/g2/ipc/watcher.py` | Host-side IPC file watcher |
| `src/g2/groups/authorization.py` | Fine-grained IPC authorization |
| `src/g2/execution/mount_security.py` | Mount allowlist validation |
| `groups/*/CLAUDE.md` | Per-group persistent memory |

## Configuration

Configuration lives in `src/g2/infrastructure/config.py`. Key environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `ASSISTANT_NAME` | `G2` | Trigger pattern and response prefix |
| `ASSISTANT_HAS_OWN_NUMBER` | `false` | If `true`, all messages trigger (no @mention needed) |
| `CONTAINER_IMAGE` | `g2-agent:latest` | Docker image for agent containers |
| `CONTAINER_TIMEOUT` | `1800000` (30min) | Max container execution time |
| `IDLE_TIMEOUT` | `1800000` (30min) | Inactivity timeout |
| `MAX_CONCURRENT_CONTAINERS` | `5` | Global concurrency limit |
| `CONTAINER_MAX_OUTPUT_SIZE` | `10485760` (10MB) | Max output size from container |

### Authentication

Add one of these to `.env` in the project root:

```bash
# Option 1: Claude subscription (OAuth token from ~/.claude/.credentials.json)
CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...

# Option 2: Pay-per-use API key
ANTHROPIC_API_KEY=sk-ant-api03-...
```

Only auth variables are extracted from `.env` and mounted into containers. Other env vars are not exposed to agents.

### Additional Mounts

Groups can have host directories mounted into their container via `containerConfig`:

```python
container_config = {
    "additional_mounts": [
        {"host_path": "~/projects/webapp", "container_path": "webapp", "readonly": False}
    ]
}
```

Mounts appear at `/workspace/extra/{containerPath}`. All mounts are validated against an allowlist at `~/.config/g2/mount-allowlist.json`.

## Memory System

G2 uses a hierarchical memory system based on CLAUDE.md files that persist across sessions.

| Level | Location | Scope |
|-------|----------|-------|
| **Global** | `groups/global/CLAUDE.md` | Read by all groups, written by main only |
| **Group** | `groups/{name}/CLAUDE.md` | Per-group context and memory |
| **Files** | `groups/{name}/*.md` | Notes, research, documents |

- Memory files are standard Markdown, auto-loaded by Claude Code
- Memory survives session clears — sessions (conversation transcripts) and memory (persistent facts) are independent
- Container filesystem isolation enforces boundaries: Group A cannot read Group B's memory
- Global memory is mounted read-only for non-main groups

## Scheduled Tasks

The built-in scheduler runs tasks as full agents in their group's context.

| Type | Format | Example |
|------|--------|---------|
| `cron` | Cron expression | `0 9 * * 1` (Mondays at 9am) |
| `interval` | Milliseconds | `3600000` (every hour) |
| `once` | ISO timestamp | `2024-12-25T09:00:00Z` |

Tasks are created conversationally:

```
@G2 remind me every Monday at 9am to review the weekly metrics
@G2 at 5pm today, send me a summary of today's emails
```

Manage tasks from any group (`@G2 list my tasks`, `pause task [id]`, `cancel task [id]`) or from the main channel for cross-group operations.

Tasks use atomic claiming to prevent double-execution, and every run is logged in `task_run_logs` with timing, status, and output.

## Security

All agents run inside containers (lightweight Linux VMs):

- **Filesystem isolation** — agents can only access mounted directories
- **Safe Bash** — commands run inside the container, not on the host
- **Non-root** — container runs as unprivileged `agent` user (uid 1000)
- **No Docker socket** — containers cannot access the container runtime
- **Read-only mounts** — global memory and reference directories are read-only
- **Timeouts** — containers killed after `CONTAINER_TIMEOUT`
- **Output limits** — responses capped at `CONTAINER_MAX_OUTPUT_SIZE`
- **Mount validation** — all paths checked against allowlist with symlink resolution and path traversal prevention
- **Authorization policy** — main group gets full access; regular groups restricted to own-group operations
- **Message sanitization** — XML encoding prevents tag injection; internal reasoning tags stripped before delivery

See [docs/SECURITY.md](docs/SECURITY.md) for the full security model.

## Customizing

There are no configuration files to learn. Just tell Claude Code what you want:

- "Change the trigger word to @Bob"
- "Remember in the future to make responses shorter and more direct"
- "Add a custom greeting when I say good morning"
- "Store conversation summaries weekly"

Or run `/customize` for guided changes.

The codebase is small enough that Claude can safely modify it.

## Skills

G2 extends through Claude Code skills rather than feature flags.

### Available Skills

| Skill | Purpose |
|-------|---------|
| `/setup` | First-time installation and configuration |
| `/customize` | Add capabilities and integrations |
| `/debug` | Container and service troubleshooting |
| `/add-telegram` | Add Telegram as a channel |
| `/add-telegram-swarm` | Agent swarm support for Telegram |
| `/add-discord` | Add Discord as a channel |
| `/add-gmail` | Gmail integration |
| `/add-voice-transcription` | Whisper voice transcription |
| `/x-integration` | X/Twitter integration |
| `/add-parallel` | Parallel agent execution |
| `/convert-to-apple-container` | Switch from Docker to Apple Container |
| `/sync-docs` | Sync documentation after refactoring |

### Skills System CLI (Experimental)

Deterministic skills-system primitives for programmatic skill management:

```bash
python scripts/init_g2_dir.py --core-version 0.5.0 --base-source .
python scripts/apply_skill.py --skill whatsapp --version 1.2.0 --files-modified src/server.py
python scripts/update_core.py preview
python scripts/update_core.py stage --target-core-version 0.6.0 --base-source /path/to/new/core
python scripts/update_core.py commit
# or: python scripts/update_core.py rollback
```

These operate on `.g2/state.yaml`, `.g2/base/`, and related state files using three-way merge with git primitives.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| No response to messages | Check service: `launchctl list \| grep g2` |
| Container exit code 1 | Check logs; verify mount is `/home/agent/.claude/` not `/root/.claude/` |
| Session not continuing | Check SQLite: `sqlite3 store/messages.db "SELECT * FROM sessions"` |
| QR code expired | Delete `store/auth/` and restart |
| No groups registered | Send `@G2 add group "Name"` in main channel |
| Container build fails | Run `docker builder prune` then `./container/build.sh` |
| Slow responses | Check `MAX_CONCURRENT_CONTAINERS` — may be queued |
| WhatsApp disconnects | Keep linked device active; sessions expire after ~20 days |

### Logs

- `logs/g2.log` — host stdout
- `logs/g2.error.log` — host stderr
- `groups/{folder}/logs/container-*.log` — per-container logs

### Debug Mode

Run manually for verbose output:

```bash
uv run python -m g2  # or: python -m g2
```

Or run `/debug` in Claude Code for guided troubleshooting.

## Contributing

**Don't add features. Add skills.**

If you want to add Telegram support, don't create a PR that adds Telegram alongside WhatsApp. Instead, contribute a skill file (`.claude/skills/add-telegram/SKILL.md`) that teaches Claude Code how to transform a G2 installation to use Telegram.

Users then run `/add-telegram` on their fork and get clean code that does exactly what they need, not a bloated system trying to support every use case.

**What gets accepted into the codebase:** Security fixes, bug fixes, and clear improvements to the base configuration. Everything else should be contributed as skills.

### RFS (Request for Skills)

Skills we'd love to see:

**Communication Channels**
- `/add-telegram` - Add Telegram as channel. Should give the user option to replace WhatsApp or add as additional channel. Also should be possible to add it as a control channel (where it can trigger actions) or just a channel that can be used in actions triggered elsewhere
- `/add-slack` - Add Slack
- `/add-discord` - Add Discord

**Platform Support**
- `/setup-windows` - Windows via WSL2 + Docker

**Session Management**
- `/add-clear` - Add a `/clear` command that compacts the conversation (summarizes context while preserving critical information in the same session). Requires figuring out how to trigger compaction programmatically via the Claude Agent SDK.

## FAQ

See [docs/FAQ.md](docs/FAQ.md) for the full list of FAQs.

## Documentation

| Document | Description |
|----------|-------------|
| [docs/SPEC.md](docs/SPEC.md) | Full specification — the authoritative reference |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture and design patterns |
| [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) | Architecture decision records |
| [docs/SECURITY.md](docs/SECURITY.md) | Security model and trust boundaries |
| [docs/CHANNEL-MANAGEMENT.md](docs/CHANNEL-MANAGEMENT.md) | Channel interface and multi-channel routing |
| [docs/MEMORY.md](docs/MEMORY.md) | Memory and session system internals |
| [docs/HEARTBEAT.md](docs/HEARTBEAT.md) | Polling loops and task scheduler |
| [docs/SDK_DEEP_DIVE.md](docs/SDK_DEEP_DIVE.md) | Claude Agent SDK integration details |
| [docs/DEBUG_CHECKLIST.md](docs/DEBUG_CHECKLIST.md) | Debugging guide and known issues |
| [docs/SKILLS-ARCHITECTURE.md](docs/SKILLS-ARCHITECTURE.md) | Skills system architecture |
| [docs/APPLE-CONTAINER-NETWORKING.md](docs/APPLE-CONTAINER-NETWORKING.md) | Apple Container networking setup |
| [docs/FAQ.md](docs/FAQ.md) | Frequently asked questions |

## License

MIT
