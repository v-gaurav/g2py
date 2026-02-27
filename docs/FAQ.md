# FAQ

## What happens when a scheduled task fires while a session is already active?

The system never runs two containers for the same group simultaneously. When a scheduled task becomes due and the group already has an active container:

1. The task is queued onto the group's pending task list.
2. The active container's stdin is closed (via IPC close sentinel), signaling it to wind down.
3. Once the active container exits, the queued task runs next — tasks are drained before pending messages.

If the task has `context_mode: 'group'`, it picks up the group's current session ID so the scheduled container shares the same conversation context.

## What is `context_mode` on a scheduled task?

The agent chooses the mode when creating a task via the `schedule_task` IPC command. There are two options:

- **`group`** — The task container resumes the group's current session, sharing ongoing conversation context. Useful for tasks like "check on this later" where continuity matters.
- **`isolated`** (default) — The task runs with no session, starting fresh. Appropriate for standalone recurring jobs like "post a daily summary" that don't need prior conversation history.

If the agent doesn't specify `context_mode`, it defaults to `isolated`.

## Does `context_mode` apply to interactive (self-chat) messages?

No. `context_mode` is only a field on scheduled tasks. When you chat with the agent interactively, `AgentExecutor` always resumes the group's current session via `SessionManager.get()` — effectively `group` mode every time.

## What folders does the main group (self-chat) container have access to?

| Container path | Host path | Access |
|---|---|---|
| `/workspace/project` | `<project-root>` | read-write |
| `/workspace/group` | `<project-root>/groups/main` | read-write |
| `/home/agent/.claude` | `<project-root>/data/sessions/main/.claude` | read-write |
| `/workspace/ipc` | `<project-root>/data/ipc/main` | read-write |
| `/app/src` | `<project-root>/container/agent-runner/src` | read-only |
| `/home/agent/.aws` | `~/.aws` (if exists) | read-only |

`<project-root>` is the G2 working directory (the directory containing `pyproject.toml`).

## What folders does a non-main group container have access to?

| Container path | Host path | Access |
|---|---|---|
| `/workspace/group` | `<project-root>/groups/<folder>` | read-write |
| `/workspace/global` | `<project-root>/groups/global` (if exists) | read-only |
| `/home/agent/.claude` | `<project-root>/data/sessions/<folder>/.claude` | read-write |
| `/workspace/ipc` | `<project-root>/data/ipc/<folder>` | read-write |
| `/app/src` | `<project-root>/container/agent-runner/src` | read-only |
| `/home/agent/.aws` | `~/.aws` (if exists) | read-only |

The key difference: non-main groups do **not** get `/workspace/project` (no access to G2 source). Instead they get a read-only `/workspace/global` mount for shared resources.

## How do containers get LLM credentials from the host?

Secrets are passed via **stdin**, never as environment variables on the Docker command line or as mounted files.

1. **Host reads `.env`** — `ContainerRunner.readSecrets()` calls `readEnvFile()` to look for `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, and AWS credentials (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`), plus `CLAUDE_CODE_USE_BEDROCK` and `AWS_REGION`.
2. **Secrets are piped via stdin** — The host writes a JSON payload (including a `secrets` field) to the container's stdin, then immediately deletes the reference from memory.
3. **Container builds an SDK env** — The agent-runner reads the JSON, merges `secrets` into a `sdkEnv` object (spread from `process.env`), and passes it to the Claude Agent SDK's `query()` call via the `env` option. Secrets are never set on `process.env` itself.
4. **Bash commands can't see secrets** — A `PreToolUse` hook prepends `unset ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN AWS_ACCESS_KEY_ID ...` to every Bash command, so shell subprocesses never inherit them.

### Can I use agent swarm mode with WhatsApp?

No. WhatsApp only supports a single bot identity per connection, so there's no way for multiple agents to appear as different senders in a group chat. Telegram supports this because each bot gets its own token, name, and avatar — multiple bots can coexist in the same group, each representing a different sub-agent.

To use swarm mode, add Telegram as a channel (`/add-telegram`), then enable swarm support (`/add-telegram-swarm`). Telegram can run alongside WhatsApp — you don't have to replace it.

### What if my `.env` only has `CLAUDE_CODE_USE_BEDROCK` and `AWS_REGION`?

That's fine. The remaining AWS credentials (`AWS_ACCESS_KEY_ID`, etc.) are resolved by the standard AWS credential chain. Since the container inherits the host's `process.env` via the `sdkEnv` spread, credentials from any of these sources work automatically:

- Environment variables set in the host shell or systemd unit
- `~/.aws/credentials` and `~/.aws/config` (mounted read-only into the container at `/home/agent/.aws`)
- IAM instance profile / EC2 metadata
- SSO cached tokens from `aws sso login`
