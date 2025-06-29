# 🎮 Zapt 1v1 Lobby System Documentation

A complete 1v1 game lobby system built with FastAPI and Supabase, featuring automatic matchmaking, manual invites, real-time WebSocket communication, and comprehensive event logging.

## 📋 Table of Contents

1. [System Overview](#system-overview)
2. [Database Schema](#database-schema)
3. [API Endpoints](#api-endpoints)
4. [WebSocket Events](#websocket-events)
5. [Event Flow Description](#event-flow-description)
6. [Authentication](#authentication)
7. [Testing](#testing)
8. [Configuration](#configuration)

## 🏗️ System Overview

The lobby system supports:
- **Automatic matchmaking** with FIFO queue
- **Manual lobby creation** with 4-character invite codes
- **Real-time updates** via WebSocket connections
- **Ready flow** with 3-second countdown
- **Automatic cleanup** when games start or players leave
- **Comprehensive logging** of all lobby events

### Architecture Components

```
├── lobby/
│   ├── models.py          # Pydantic models & enums
│   ├── routes.py          # HTTP API endpoints
│   ├── websocket.py       # WebSocket handler & real-time events
│   ├── matchmaking.py     # FIFO queue logic
│   └── utils.py           # Code generation, logging, helpers
├── main.py                # FastAPI app with integrations
├── lobby_test_client.html # HTML test client
└── lobby_events.log       # Auto-generated event log
```

## 📊 Database Schema

### Lobbies Table
```sql
CREATE TABLE lobbies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(4) UNIQUE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'waiting' 
        CHECK (status IN ('waiting', 'ready_check', 'countdown', 'game_started')),
    max_players INTEGER NOT NULL DEFAULT 2,
    current_players INTEGER NOT NULL DEFAULT 0,
    countdown_start_time TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### Lobby Members Table
```sql
CREATE TABLE lobby_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lobby_id UUID NOT NULL REFERENCES lobbies(id) ON DELETE CASCADE,
    device_id TEXT NOT NULL REFERENCES players(device_id) ON DELETE CASCADE,
    is_ready BOOLEAN NOT NULL DEFAULT FALSE,
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(lobby_id, device_id)
);
```

### Matchmaking Queue Table
```sql
CREATE TABLE matchmaking_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id TEXT NOT NULL REFERENCES players(device_id) ON DELETE CASCADE,
    queue_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(device_id)
);
```

## 🔌 API Endpoints

### Authentication
All endpoints require `X-Device-ID` header for player identification.

### Lobby Management

#### `POST /lobby/create`
Create a new lobby with random 4-character code.

**Request:** `{}`
**Response:**
```json
{
  "success": true,
  "lobby": {
    "id": "uuid",
    "code": "ABCD",
    "status": "waiting",
    "max_players": 2,
    "current_players": 1,
    "players": [
      {
        "device_id": "test_device_1",
        "user_name": "Player1",
        "is_ready": false,
        "joined_at": "2024-01-01T12:00:00Z"
      }
    ],
    "countdown_start_time": null,
    "created_at": "2024-01-01T12:00:00Z"
  },
  "message": "Lobby created with code: ABCD"
}
```

#### `POST /lobby/join`
Join existing lobby by code.

**Request:**
```json
{
  "code": "ABCD"
}
```

**Response:** Same as create response with updated player list.

#### `POST /lobby/leave`
Leave current lobby.

**Request:** `{}`
**Response:**
```json
{
  "success": true,
  "message": "Successfully left lobby"
}
```

#### `POST /lobby/ready`
Toggle ready status.

**Request:**
```json
{
  "is_ready": true
}
```

**Response:** Updated lobby info with new ready states.

#### `GET /lobby/status`
Get current lobby status.

**Response:** Current lobby information or "not in lobby" message.

### Matchmaking

#### `POST /lobby/find_match`
Enter matchmaking queue or get matched.

**Request:** `{}`
**Response (Queue):**
```json
{
  "success": true,
  "in_queue": true,
  "estimated_wait_time": 30,
  "queue_position": 1,
  "message": "Added to matchmaking queue. Waiting for opponent..."
}
```

**Response (Match Found):**
```json
{
  "success": true,
  "in_queue": false,
  "message": "Match found! Lobby created.",
  "lobby": { /* lobby object */ }
}
```

#### `POST /lobby/leave_queue`
Leave matchmaking queue.

#### `GET /lobby/queue_status`
Check current queue status.

## 🔄 WebSocket Events

### Connection
Connect to: `ws://localhost:8000/ws/lobby/{lobby_code}?device_id={device_id}`

### Event Types

#### `player_joined`
```json
{
  "type": "player_joined",
  "data": {
    "player": {
      "device_id": "test_device_2",
      "user_name": "Player2",
      "is_ready": false,
      "joined_at": "2024-01-01T12:01:00Z"
    },
    "lobby": { /* full lobby object */ }
  },
  "timestamp": "2024-01-01T12:01:00Z"
}
```

#### `player_left`
```json
{
  "type": "player_left",
  "data": {
    "device_id": "test_device_2",
    "lobby": { /* updated lobby object */ }
  }
}
```

#### `ready_status_changed`
```json
{
  "type": "ready_status_changed",
  "data": {
    "device_id": "test_device_1",
    "is_ready": true,
    "lobby": { /* updated lobby object */ }
  }
}
```

#### `countdown_started`
```json
{
  "type": "countdown_started",
  "data": {
    "lobby": { /* lobby object with countdown_start_time */ }
  }
}
```

#### `countdown_tick`
```json
{
  "type": "countdown_tick",
  "data": {
    "seconds_remaining": 2
  }
}
```

#### `countdown_aborted`
```json
{
  "type": "countdown_aborted",
  "data": {
    "lobby": { /* lobby object back to ready_check status */ }
  }
}
```

#### `game_started`
```json
{
  "type": "game_started",
  "data": {
    "lobby_code": "ABCD"
  }
}
```

#### `lobby_deleted`
```json
{
  "type": "lobby_deleted",
  "data": {
    "reason": "game_started" // or "empty"
  }
}
```

## 📋 Event Flow Description

### Manual Lobby Creation Flow

1. **Player creates lobby**: `POST /lobby/create`
   - Generate unique 4-character code
   - Create lobby record in database
   - Add creator as member
   - Log: `lobby_created`

2. **Second player joins**: `POST /lobby/join`
   - Validate lobby exists and has space
   - Add player to lobby_members
   - Update lobby current_players count
   - Broadcast: `player_joined` via WebSocket
   - Log: `lobby_joined`

3. **Players set ready**: `POST /lobby/ready`
   - Update member's is_ready status
   - Check if all players ready
   - If all ready → status: `ready_check`
   - Broadcast: `ready_status_changed`
   - Log: `ready_toggle`

4. **Countdown starts**: When both ready
   - Status: `countdown` 
   - Set countdown_start_time
   - Start 3-second countdown task
   - Broadcast: `countdown_started`, then `countdown_tick` each second
   - Log: `countdown_started`

5. **Game starts**: After countdown
   - Status: `game_started`
   - Broadcast: `game_started`
   - Delete lobby from database after 2 seconds
   - Broadcast: `lobby_deleted`
   - Close all WebSocket connections
   - Log: `game_started`, `lobby_deleted`

### Matchmaking Flow

1. **Player enters queue**: `POST /lobby/find_match`
   - Check if anyone waiting in queue
   - If no one waiting: Add to matchmaking_queue
   - If someone waiting: Create lobby with both players, remove from queue
   - Log: `matchmaking_queue_join` or `matchmaking_match_found`

2. **Match found**: Automatic lobby creation
   - Create lobby with both players
   - Both players start as not ready
   - Continue with normal ready flow

### Edge Case Handling

#### Player Disconnects During Countdown
1. WebSocket connection lost
2. Player automatically removed from lobby
3. Countdown aborted immediately
4. Remaining player reset to unready
5. Lobby status back to `waiting`
6. Broadcast: `countdown_aborted`, `player_left`
7. Log: `lobby_left_on_disconnect`, `countdown_aborted`

#### Last Player Leaves
1. Player leaves lobby
2. Lobby becomes empty (current_players = 0)
3. Lobby record deleted from database
4. Any running countdown cancelled
5. Log: `lobby_deleted` with reason "empty"

#### Lobby Code Collision
- System tries up to 10 random codes
- If all fail, uses timestamp-based fallback
- Ensures uniqueness in database

## 🔐 Authentication

### Current Implementation (MVP)
- Simple device_id header authentication
- Header: `X-Device-ID: your_device_id`
- No JWT validation for testing purposes

### Production Ready (Future)
```python
# Add JWT validation to routes.py
async def get_device_id(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid authorization header")
    
    token = authorization.split(" ")[1]
    # Validate JWT with Supabase
    user = supabase.auth.get_user(token)
    return user.user.id
```

## 🧪 Testing

### Using the HTML Test Client

1. **Start the server**: `python main.py`
2. **Open**: `lobby_test_client.html` in browser
3. **Set Device ID**: Enter unique device ID for testing
4. **Test Scenarios**:

#### Test Matchmaking
1. Open two browser tabs
2. Set different device IDs in each
3. Click "Find Match" in both
4. Second click should create lobby automatically

#### Test Manual Lobby
1. Create lobby in first tab
2. Note the 4-character code
3. Join with code in second tab
4. Test ready states and countdown

#### Test WebSocket
1. After joining lobby, click "Connect to Lobby WebSocket"
2. Ready/unready in one tab
3. Watch real-time updates in other tab

### API Testing with curl

```bash
# Create player first
curl -X POST "http://localhost:8000/players" \
  -H "Content-Type: application/json" \
  -d '{"device_id": "test_device_1"}'

# Create lobby
curl -X POST "http://localhost:8000/lobby/create" \
  -H "X-Device-ID: test_device_1" \
  -H "Content-Type: application/json" \
  -d '{}'

# Join lobby
curl -X POST "http://localhost:8000/lobby/join" \
  -H "X-Device-ID: test_device_2" \
  -H "Content-Type: application/json" \
  -d '{"code": "ABCD"}'

# Set ready
curl -X POST "http://localhost:8000/lobby/ready" \
  -H "X-Device-ID: test_device_1" \
  -H "Content-Type: application/json" \
  -d '{"is_ready": true}'
```

## ⚙️ Configuration

### Environment Variables
```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
```

### Supabase Setup
The system automatically creates the required tables via migration. Your Supabase project needs:
1. The existing `players` table
2. RLS policies (optional for development)
3. Anonymous access for the anon key

### Customization Options

#### Change Countdown Duration
```python
# In websocket.py, _countdown_worker method
for remaining in range(5, -1, -1):  # 5-second countdown
```

#### Change Lobby Code Length
```python
# In utils.py, generate_lobby_code function
return ''.join(random.choice(clear_chars) for _ in range(6))  # 6-character codes
```

#### Change Max Players
```python
# In routes.py, lobby creation
lobby_data = {
    "max_players": 4,  # 4-player lobbies
    # ...
}
```

## 📁 File Structure

```
Zapt/
├── lobby/
│   ├── __init__.py         # Package initialization
│   ├── models.py           # Pydantic models, enums, type definitions
│   ├── routes.py           # HTTP endpoints, business logic
│   ├── websocket.py        # WebSocket handler, real-time events
│   ├── matchmaking.py      # FIFO queue, automatic matching
│   └── utils.py            # Utilities, logging, code generation
├── main.py                 # FastAPI app with lobby integration
├── lobby_test_client.html  # Interactive test client
├── lobby_events.log        # Auto-generated event log
├── requirements.txt        # Dependencies
└── LOBBY_SYSTEM_DOCUMENTATION.md
```

## 🚀 Production Considerations

1. **Scale WebSocket Connections**: Use Redis for multi-server WebSocket management
2. **Database Optimization**: Add more indexes for high-traffic queries
3. **Rate Limiting**: Add rate limits to prevent API abuse
4. **Monitoring**: Implement health checks and metrics
5. **Error Recovery**: Add retry logic for critical operations
6. **Security**: Implement proper JWT validation
7. **Load Testing**: Test with many concurrent lobbies

---

**Built with ❤️ for Zapt - Ready for production deployment!** 