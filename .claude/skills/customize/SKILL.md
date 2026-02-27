---
name: customize
description: Add new capabilities or modify G2 behavior. Use when user wants to add channels (Telegram, Slack, email input), change triggers, add integrations, modify the router, or make any other customizations. This is an interactive skill that asks questions to understand what the user wants.
---

# G2 Customization

This skill helps users add capabilities or modify behavior. Use AskUserQuestion to understand what they want before making changes.

## Workflow

1. **Understand the request** - Ask clarifying questions
2. **Plan the changes** - Identify files to modify
3. **Implement** - Make changes directly to the code
4. **Test guidance** - Tell user how to verify

## Key Files

| File | Purpose |
|------|---------|
| `src/g2/__main__.py` | Entry point: `python -m g2` bootstrap |
| `src/g2/app.py` | Orchestrator class: composes services, wires subsystems |
| `src/g2/messaging/whatsapp/channel.py` | WhatsApp connection, auth, send/receive (neonize) |
| `src/g2/messaging/types.py` | `Channel` Protocol, `OnInboundMessage`, `OnChatMetadata`, `NewMessage` |
| `src/g2/messaging/channel_registry.py` | Registry pattern for multiple channels |
| `src/g2/ipc/watcher.py` | IPC watcher (watchfiles + fallback poll) |
| `src/g2/ipc/dispatcher.py` | Routes IPC commands to handlers |
| `src/g2/types.py` | Barrel re-export of all domain types |
| `src/g2/infrastructure/config.py` | Trigger pattern, paths, intervals, container settings, `.env` parsing |
| `src/g2/infrastructure/database.py` | Schema creation, migrations, `AppDatabase` composition root |
| `groups/CLAUDE.md` | Global memory/persona |

## Common Customization Patterns

### Adding a New Input Channel (e.g., Telegram, Slack, Discord)

Questions to ask:
- Which channel? (Telegram, Slack, Discord, SMS, etc.)
- Same trigger word or different?
- Same memory hierarchy or separate?
- Should messages from this channel go to existing groups or new ones?

Implementation pattern:
1. Create `src/g2/messaging/{name}/channel.py` implementing the `Channel` Protocol from `src/g2/messaging/types.py` (see `src/g2/messaging/whatsapp/channel.py` for reference)
2. Register the channel in `src/g2/app.py` via the `ChannelRegistry`
3. Messages are stored via the `on_inbound_message` callback; routing is automatic via `owns_jid()`

### Adding a New MCP Integration

Questions to ask:
- What service? (Calendar, Notion, database, etc.)
- What operations needed? (read, write, both)
- Which groups should have access?

Implementation:
1. Add MCP server config to the container settings (see `src/g2/execution/container_runner.py` for how MCP servers are mounted)
2. Document available tools in `groups/CLAUDE.md`

### Changing Assistant Behavior

Questions to ask:
- What aspect? (name, trigger, persona, response style)
- Apply to all groups or specific ones?

Simple changes → edit `src/g2/infrastructure/config.py`
Persona changes → edit `groups/CLAUDE.md`
Per-group behavior → edit specific group's `CLAUDE.md`

### Adding New Commands

Questions to ask:
- What should the command do?
- Available in all groups or main only?
- Does it need new MCP tools?

Implementation:
1. Commands are handled by the agent naturally — add instructions to `groups/CLAUDE.md` or the group's `CLAUDE.md`
2. For trigger-level routing changes, modify the message processing in `src/g2/messaging/poller.py`

### Changing Deployment

Questions to ask:
- Target platform? (Linux server, Docker, different Mac)
- Service manager? (systemd, Docker, supervisord)

Implementation:
1. Create appropriate service files
2. Update paths in config
3. Provide setup instructions

## After Changes

Always tell the user:
```bash
# Restart the service (no build step needed — Python runs directly)
# Linux:
systemctl --user restart g2

# macOS:
launchctl kickstart -k gui/$(id -u)/com.g2
```

Or use the `/restart` skill.

## Example Interaction

User: "Add Telegram as an input channel"

1. Ask: "Should Telegram use the same @G2 trigger, or a different one?"
2. Ask: "Should Telegram messages create separate conversation contexts, or share with WhatsApp groups?"
3. Create `src/g2/messaging/telegram/channel.py` implementing the `Channel` Protocol (see `src/g2/messaging/whatsapp/channel.py`)
4. Register the channel in `src/g2/app.py`
5. Tell user how to authenticate and test
