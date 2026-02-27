# Channel Management

How G2 connects to messaging platforms, routes messages, and supports multi-channel operation.

---

## Overview

G2 uses a pluggable channel architecture to abstract messaging platforms. Each channel implements a minimal interface, registers with a central registry, and routes messages by JID (Jabber ID) pattern. The system currently ships with WhatsApp and is extensible to Telegram, Discord, and other platforms via skills.

```
User ──> Channel (WhatsApp) ──> SQLite ──> Polling Loop ──> Container (Agent)
                                                                  │
                                                            IPC send_message
                                                                  │
                                          Channel Registry ◄──────┘
                                                │
                                          Channel.send_message()
                                                │
                                          User ◄─┘
```

---

## Channel Interface

Defined in `src/g2/messaging/types.py`:

```python
class Channel(Protocol):
    name: str

    async def connect(self) -> None: ...
    async def send_message(self, jid: str, text: str) -> None: ...
    def is_connected(self) -> bool: ...
    def owns_jid(self, jid: str) -> bool: ...
    async def disconnect(self) -> None: ...
    async def set_typing(self, jid: str, is_typing: bool) -> None: ...
    async def sync_metadata(self, force: bool = False) -> None: ...
```

| Method | Required | Purpose |
|--------|----------|---------|
| `name` | yes | Unique identifier (`'whatsapp'`, `'telegram'`, `'discord'`) |
| `connect()` | yes | Initialize connection to the platform |
| `send_message()` | yes | Deliver a text message to a JID |
| `is_connected()` | yes | Connection health check |
| `owns_jid()` | yes | JID pattern ownership — determines routing |
| `disconnect()` | yes | Graceful teardown |
| `set_typing()` | no | Typing indicator (composing/paused) |
| `sync_metadata()` | no | Sync chat/group names from platform |

**Callback types** (`src/g2/messaging/types.py`):

| Type | Purpose |
|------|---------|
| `OnInboundMessage` | Channel delivers a parsed message to the host |
| `OnChatMetadata` | Channel notifies the host about chat discovery (JID, name, timestamp) |

Channels are passive — they receive messages via platform-specific listeners and deliver them through callbacks. The host's polling loop is the active orchestrator.

---

## Channel Registry

`src/g2/messaging/channel_registry.py` — the central routing hub for all channels.

### Registration

```python
channel_registry = ChannelRegistry()
channel_registry.register(whatsapp)   # Enforces unique names
```

Duplicate channel names throw an error. Registration happens once during startup.

### JID-Based Routing

The registry routes outbound messages to the correct channel by asking each channel if it owns the target JID:

| JID Pattern | Channel | `owns_jid()` logic |
|-------------|---------|-------------------|
| `*@g.us` | WhatsApp | Group chat |
| `*@s.whatsapp.net` | WhatsApp | Individual chat |
| `tg:*` | Telegram | Prefixed with `tg:` |
| `dc:*` | Discord | Prefixed with `dc:` |

### Key Methods

| Method | Purpose |
|--------|---------|
| `find_by_jid(jid)` | Find channel that owns this JID (any state) |
| `find_connected_by_jid(jid)` | Find channel that owns this JID **and** is connected |
| `get_all()` | Return all registered channels |
| `sync_all_metadata(force?)` | Trigger metadata sync on all channels that support it |
| `disconnect_all()` | Gracefully disconnect all channels |

`find_connected_by_jid()` is used for all outbound sends — a disconnected channel's messages are queued internally by the channel (see [Message Queue](#outgoing-message-queue)).

---

## Inbound Message Flow

### Step 1: Platform Event → Channel Callback

The channel listens for platform-specific events and translates them into the common `NewMessage` type.

**WhatsApp example** (`src/g2/messaging/whatsapp/channel.py`):

1. Neonize emits message event
2. Channel filters out empty messages and status broadcasts
3. Translates LID JIDs to phone JIDs for consistency
4. Calls `on_chat_metadata()` for all messages (enables group discovery)
5. Calls `on_message()` only for registered groups
6. Detects bot messages via `from_me` flag (own number) or assistant name prefix (shared number)

### Step 2: Callback → SQLite

Callbacks defined in `src/g2/app.py`:

```python
on_message=lambda chat_jid, msg: store_message(msg),
on_chat_metadata=lambda chat_jid, ts, name, channel, is_group: store_chat_metadata(...),
```

Messages are stored in the `messages` table, chat metadata in the `chats` table. The `chats` table tracks `channel` (e.g., `'whatsapp'`, `'telegram'`) and `is_group` per JID.

### Step 3: Polling Loop → Container

`MessagePoller.start_polling()` (in `src/g2/messaging/poller.py`) runs every `POLL_INTERVAL` (2s):

1. `get_new_messages()` fetches messages since `last_timestamp`
2. Deduplicates by group (one container per group per cycle)
3. Checks trigger pattern (main group always active; others require `@G2` mention)
4. Fetches full message history since `last_agent_timestamp[group]`
5. `format_messages()` converts to XML for the agent
6. Enqueues to `ExecutionQueue` for container processing

### Cursor Management (Exactly-Once Processing)

| Cursor | Scope | Purpose |
|--------|-------|---------|
| `last_timestamp` | Global | Polling cursor — advanced after reading new messages |
| `last_agent_timestamp[group]` | Per-group | Advanced **before** running agent to prevent reprocessing |

- On error **before** user output: cursor rolled back for retry
- On error **after** user output: cursor kept to prevent duplicate responses

---

## Outbound Message Flow

### Step 1: Agent → IPC

The agent calls the `send_message` MCP tool, which writes a JSON file to `/workspace/ipc/messages/`:

```json
{
  "type": "message",
  "chatJid": "123456789-987654321@g.us",
  "text": "Hello from agent"
}
```

### Step 2: IPC → Authorization

The host's IPC watcher (`src/g2/ipc/watcher.py`) detects the file and checks authorization (`src/g2/groups/authorization.py`):

| Caller | Can send to own group | Can send to other groups |
|--------|----------------------|-------------------------|
| Main group | yes | yes |
| Non-main group | yes | no |

Unauthorized sends are blocked and logged.

### Step 3: Authorization → Channel Registry → Channel

```python
channel = channel_registry.find_connected_by_jid(jid)
channel.send_message(jid, text)
```

The registry finds the correct channel by JID pattern. The channel handles platform-specific formatting and delivery.

### Step 4: Outbound Formatting

`src/g2/messaging/formatter.py` processes agent output before sending:

1. `MessageFormatter.strip_internal_tags()` — removes `<internal>...</internal>` reasoning blocks
2. Empty strings after stripping are discarded (no empty messages sent)

### Task Scheduler Output

Scheduled tasks (`src/g2/scheduling/scheduler.py`) follow the same outbound path. The scheduler calls `channel_registry.find_connected_by_jid()` to route task output. Scheduled task output is not sent automatically — the agent must explicitly use `send_message`.

---

## WhatsApp Channel

`src/g2/messaging/whatsapp/channel.py` — the primary channel implementation.

### Connection

- Uses [neonize](https://github.com/krypton-byte/neonize) for WhatsApp Web connection
- Auth state stored in `store/auth/` directory
- Requires prior authentication via `/setup` skill (QR code triggers exit if unauthenticated)

### Configuration

| Setting | Source | Purpose |
|---------|--------|---------|
| `ASSISTANT_NAME` | `.env` / `src/g2/infrastructure/config.py` | Bot name prefix on shared numbers |
| `ASSISTANT_HAS_OWN_NUMBER` | `.env` / `src/g2/infrastructure/config.py` | If `true`, skip name prefix and use `from_me` for bot detection |

### Bot Message Detection

Two modes depending on phone number setup:

| Mode | Detection | Prefix |
|------|-----------|--------|
| Own number (`ASSISTANT_HAS_OWN_NUMBER=true`) | `msg.key.from_me` flag | None — WhatsApp shows the number identity |
| Shared number | Content starts with `{ASSISTANT_NAME}:` | `{ASSISTANT_NAME}: ` prepended to all outbound |

### LID Translation

WhatsApp uses Legacy IDs (LIDs) for multi-device support. The channel translates LID JIDs to phone JIDs (`src/g2/messaging/whatsapp/channel.py`):

1. Check local cache (`lid_to_phone_map`)
2. Query neonize's contact store
3. Fall back to raw LID if unresolvable

### Reconnection

Exponential backoff with jitter (`src/g2/messaging/whatsapp/channel.py`):

| Parameter | Value |
|-----------|-------|
| Base delay | 2 seconds |
| Max delay | 60 seconds |
| Max retries | 10 |
| Backoff formula | `min(2s * 2^attempt, 60s)` |

Reconnection resets on successful connection. Logged-out status (reason `logged_out`) triggers process exit instead of reconnect.

### Typing Indicators

`set_typing(jid, is_typing)` sends `composing` or `paused` presence updates. Errors are silently caught (typing is best-effort).

---

## Outgoing Message Queue

`src/g2/messaging/whatsapp/outgoing_queue.py` — buffers messages when a channel is disconnected.

### Behavior

- FIFO ordered delivery
- Messages are only removed after successful send (peek-then-shift)
- Prevents duplicate flushing via `flushing` mutex flag
- Flushed automatically when the channel reconnects (`on_connection_open`)

### Flow

```
send_message() ──> connected? ──yes──> client.send_message()
                      │
                     no
                      │
                      ▼
              message_queue.enqueue()
                      │
              [channel reconnects]
                      │
                      ▼
              message_queue.flush() ──> client.send_message() per item
```

Send failures also trigger queueing — if `client.send_message()` throws, the message is queued for retry on reconnect.

---

## Metadata Synchronization

`src/g2/messaging/whatsapp/metadata_sync.py` — syncs group names from WhatsApp into the database.

### Timing

| Event | Behavior |
|-------|----------|
| Startup | Sync immediately (respects 24h cache) |
| Periodic | Every 24 hours via polling loop |
| On demand | Via `refresh_groups` IPC command (force bypass cache) |

### Cache

- Last sync timestamp stored in SQLite (`get_last_group_sync()` / `set_last_group_sync()`)
- Corrupted timestamps (NaN) fall through to sync (safe default)
- `force=true` bypasses cache entirely

### Data Flow

1. Call `client.get_joined_groups()` to get all WhatsApp groups
2. For each group with a `subject`, call `update_chat_name(jid, subject)`
3. Update sync timestamp

---

## Database Schema

Channel-related tables in `store/messages.db` (managed by `src/g2/infrastructure/database.py`):

### `chats` Table

| Column | Type | Purpose |
|--------|------|---------|
| `jid` | TEXT PRIMARY KEY | Chat identifier (JID) |
| `name` | TEXT | Human-readable chat/group name |
| `last_message_time` | TEXT | ISO timestamp of last message |
| `channel` | TEXT | Source channel (`'whatsapp'`, `'telegram'`, `'discord'`) |
| `is_group` | INTEGER | `1` for group chats, `0` for individual |

### `messages` Table

| Column | Type | Purpose |
|--------|------|---------|
| `id` | TEXT | Message ID (platform-specific) |
| `chat_jid` | TEXT | Foreign key to `chats.jid` |
| `sender` | TEXT | Sender JID |
| `sender_name` | TEXT | Display name (push name) |
| `content` | TEXT | Message text content |
| `timestamp` | TEXT | ISO timestamp |
| `is_from_me` | INTEGER | `1` if sent by the connected account |
| `is_bot_message` | INTEGER | `1` if detected as bot output |

### Channel Detection (Migration)

The `channel` and `is_group` columns are derived from JID patterns:

| JID Pattern | Channel | Is Group |
|-------------|---------|----------|
| `*@g.us` | `whatsapp` | `1` |
| `*@s.whatsapp.net` | `whatsapp` | `0` |
| `tg:*` | `telegram` | `1` |
| `dc:*` | `discord` | `1` |

---

## Adding a New Channel

To add a new messaging platform (e.g., Telegram, Discord):

### 1. Implement the `Channel` Interface

Create `src/g2/messaging/{platform}/channel.py`:

```python
# Create src/g2/messaging/{platform}/channel.py

class TelegramChannel:
    name = "telegram"

    async def connect(self) -> None:
        """Platform init."""
        ...

    async def send_message(self, jid: str, text: str) -> None:
        """Send message."""
        ...

    def is_connected(self) -> bool:
        """Check connection."""
        ...

    def owns_jid(self, jid: str) -> bool:
        return jid.startswith("tg:")

    async def disconnect(self) -> None:
        """Cleanup."""
        ...
```

### 2. Register in Main

In `src/g2/app.py`:

```python
# In src/g2/app.py
telegram = TelegramChannel(channel_opts)
channel_registry.register(telegram)
await telegram.connect()
```

### 3. JID Routing Auto-Resolves

Once registered, `channel_registry.find_connected_by_jid()` automatically routes messages to the new channel based on `owns_jid()`. No changes needed to the router, IPC layer, or agent code.

### 4. Database Migration

Add a migration to classify existing JIDs:

```sql
UPDATE chats SET channel = 'telegram', is_group = 1 WHERE jid LIKE 'tg:%';
```

### Available Skills

G2 provides skills for adding channels:

| Skill | Platform | JID Pattern |
|-------|----------|-------------|
| `/add-telegram` | Telegram | `tg:*` |
| (add-discord) | Discord | `dc:*` |
| `/add-gmail` | Gmail | Platform-specific |

---

## Graceful Shutdown

On `SIGTERM` or `SIGINT` (`src/g2/app.py` — `shutdown()`):

```python
# 1. queue.shutdown(timeout=10.0) — drain active containers
# 2. channel_registry.disconnect_all() — disconnect every channel
# 3. sys.exit(0)
```

Each channel's `disconnect()` handles platform-specific cleanup (e.g., closing WebSocket connections).

---

## Source Files

| File | Purpose |
|------|---------|
| `src/g2/messaging/types.py` | `Channel` Protocol, `OnInboundMessage`, `OnChatMetadata` callbacks |
| `src/g2/messaging/channel_registry.py` | `ChannelRegistry` — registration, JID routing, bulk operations |
| `src/g2/messaging/whatsapp/channel.py` | `WhatsAppChannel` — neonize connection, send/receive, LID translation |
| `src/g2/messaging/whatsapp/outgoing_queue.py` | `OutgoingMessageQueue` — FIFO buffer for disconnection resilience |
| `src/g2/messaging/whatsapp/metadata_sync.py` | `WhatsAppMetadataSync` — group name sync with 24h cache |
| `src/g2/messaging/formatter.py` | `MessageFormatter` — `format_messages()`, `format_outbound()`, `strip_internal_tags()` |
| `src/g2/groups/authorization.py` | `AuthorizationPolicy` class for fine-grained IPC auth |
| `src/g2/infrastructure/database.py` | Schema, migrations, DB init logic |
| `src/g2/infrastructure/config.py` | `ASSISTANT_NAME`, `ASSISTANT_HAS_OWN_NUMBER`, `STORE_DIR` |
| `src/g2/__main__.py` | Entry point: channel setup, callback wiring, `main()` bootstrap |
| `src/g2/app.py` | `App` — composes services, wires subsystems, shutdown |
| `src/g2/messaging/poller.py` | `MessagePoller` — message polling, cursor management, trigger checking |
| `src/g2/execution/agent_executor.py` | `AgentExecutor` — container execution, session tracking, snapshot writing |
