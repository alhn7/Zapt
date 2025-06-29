from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from enum import Enum

# Enums
class LobbyStatus(str, Enum):
    WAITING = "waiting"
    READY_CHECK = "ready_check"
    COUNTDOWN = "countdown"
    GAME_STARTED = "game_started"

class WebSocketEventType(str, Enum):
    PLAYER_JOINED = "player_joined"
    PLAYER_LEFT = "player_left"
    READY_STATUS_CHANGED = "ready_status_changed"
    COUNTDOWN_STARTED = "countdown_started"
    COUNTDOWN_ABORTED = "countdown_aborted"
    COUNTDOWN_TICK = "countdown_tick"
    GAME_STARTED = "game_started"
    LOBBY_DELETED = "lobby_deleted"
    ERROR = "error"

# Database Models
class LobbyDB(BaseModel):
    id: str
    code: str
    status: LobbyStatus
    max_players: int
    current_players: int
    countdown_start_time: Optional[datetime]
    created_at: datetime
    updated_at: datetime

class LobbyMemberDB(BaseModel):
    id: str
    lobby_id: str
    device_id: str
    is_ready: bool
    joined_at: datetime

class MatchmakingQueueDB(BaseModel):
    id: str
    device_id: str
    queue_time: datetime

# Request Models
class CreateLobbyRequest(BaseModel):
    pass  # No additional data needed for lobby creation

class JoinLobbyRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=4, description="4-character lobby code")

class FindMatchRequest(BaseModel):
    pass  # No additional data needed for matchmaking

class ReadyToggleRequest(BaseModel):
    is_ready: bool = Field(..., description="Ready status to set")

# Response Models
class PlayerInfo(BaseModel):
    device_id: str
    user_name: Optional[str]
    is_ready: bool
    joined_at: datetime

class LobbyInfo(BaseModel):
    id: str
    code: str
    status: LobbyStatus
    max_players: int
    current_players: int
    players: List[PlayerInfo]
    countdown_start_time: Optional[datetime]
    created_at: datetime

class LobbyResponse(BaseModel):
    success: bool
    lobby: Optional[LobbyInfo] = None
    message: Optional[str] = None

class MatchmakingResponse(BaseModel):
    success: bool
    in_queue: bool = False
    estimated_wait_time: Optional[int] = None  # seconds
    queue_position: Optional[int] = None
    message: Optional[str] = None
    lobby: Optional[LobbyInfo] = None  # Set when match is found

# WebSocket Models
class WebSocketMessage(BaseModel):
    type: WebSocketEventType
    data: dict
    timestamp: datetime = Field(default_factory=datetime.now)

class PlayerJoinedData(BaseModel):
    player: PlayerInfo
    lobby: LobbyInfo

class PlayerLeftData(BaseModel):
    device_id: str
    lobby: LobbyInfo

class ReadyStatusData(BaseModel):
    device_id: str
    is_ready: bool
    lobby: LobbyInfo

class CountdownData(BaseModel):
    seconds_remaining: int
    lobby: LobbyInfo

class ErrorData(BaseModel):
    error_code: str
    message: str

# Internal Models for Business Logic
class LobbyWithMembers(BaseModel):
    lobby: LobbyDB
    members: List[LobbyMemberDB]
    
    def to_lobby_info(self, players_data: dict = None) -> LobbyInfo:
        """Convert to LobbyInfo with optional player data from database"""
        players = []
        for member in self.members:
            player_data = players_data.get(member.device_id) if players_data else None
            players.append(PlayerInfo(
                device_id=member.device_id,
                user_name=player_data.get('user_name') if player_data else None,
                is_ready=member.is_ready,
                joined_at=member.joined_at
            ))
        
        return LobbyInfo(
            id=self.lobby.id,
            code=self.lobby.code,
            status=self.lobby.status,
            max_players=self.lobby.max_players,
            current_players=self.lobby.current_players,
            players=players,
            countdown_start_time=self.lobby.countdown_start_time,
            created_at=self.lobby.created_at
        ) 