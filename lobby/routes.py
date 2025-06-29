from fastapi import APIRouter, HTTPException, Depends, Header
from typing import Optional
from datetime import datetime
from supabase import Client

from .models import (
    CreateLobbyRequest, JoinLobbyRequest, FindMatchRequest, ReadyToggleRequest,
    LobbyResponse, MatchmakingResponse, LobbyStatus, LobbyDB, LobbyMemberDB,
    LobbyWithMembers, PlayerInfo, LobbyInfo
)
from .utils import (
    generate_lobby_code, log_lobby_event, validate_device_id, 
    get_lobby_summary, is_valid_lobby_code
)
from .matchmaking import MatchmakingService

# Create router
lobby_router = APIRouter(prefix="/lobby", tags=["Lobby"])

# Dependency to get device_id from header (simplified - no JWT for MVP)
async def get_device_id(device_id: Optional[str] = Header(None, alias="X-Device-ID")):
    """Extract device_id from header for authentication"""
    if not device_id or not validate_device_id(device_id):
        raise HTTPException(
            status_code=401, 
            detail={"error": "unauthorized", "message": "Valid device_id required in X-Device-ID header"}
        )
    return device_id

# Dependency injection for supabase client
def get_supabase():
    """This will be overridden when integrating with main.py"""
    raise HTTPException(status_code=500, detail="Supabase client not configured")

class LobbyService:
    """Service class for lobby operations"""
    
    def __init__(self, supabase: Client):
        self.supabase = supabase
        self.matchmaking = MatchmakingService(supabase)
    
    async def create_lobby(self, device_id: str) -> LobbyResponse:
        """Create a new lobby with a random code"""
        try:
            # Check if player is already in a lobby
            existing_member = self.supabase.table("lobby_members")\
                .select("lobby_id")\
                .eq("device_id", device_id)\
                .execute()
            
            if existing_member.data:
                return LobbyResponse(
                    success=False,
                    lobby=None,
                    message="Player is already in a lobby"
                )
            
            # Remove from matchmaking queue if present
            await self.matchmaking.leave_queue(device_id)
            
            # Generate unique code
            code = await self._generate_unique_code()
            
            # Create lobby
            lobby_data = {
                "code": code,
                "status": LobbyStatus.WAITING.value,
                "max_players": 2,
                "current_players": 1,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
            
            lobby_result = self.supabase.table("lobbies")\
                .insert(lobby_data)\
                .execute()
            
            if not lobby_result.data:
                raise Exception("Failed to create lobby")
            
            lobby_id = lobby_result.data[0]["id"]
            
            # Add creator to lobby
            member_data = {
                "lobby_id": lobby_id,
                "device_id": device_id,
                "is_ready": False,
                "joined_at": datetime.now().isoformat()
            }
            
            member_result = self.supabase.table("lobby_members")\
                .insert(member_data)\
                .execute()
            
            if not member_result.data:
                # Cleanup lobby if member creation fails
                self.supabase.table("lobbies").delete().eq("id", lobby_id).execute()
                raise Exception("Failed to add creator to lobby")
            
            # Create response
            lobby = LobbyDB(**lobby_result.data[0])
            member = LobbyMemberDB(**member_result.data[0])
            lobby_with_members = LobbyWithMembers(lobby=lobby, members=[member])
            
            log_lobby_event("lobby_created", {
                "lobby_code": code,
                "creator": device_id
            }, device_id)
            
            return LobbyResponse(
                success=True,
                lobby=lobby_with_members.to_lobby_info(),
                message=f"Lobby created with code: {code}"
            )
            
        except Exception as e:
            log_lobby_event("lobby_create_error", {
                "device_id": device_id,
                "error": str(e)
            }, device_id)
            
            return LobbyResponse(
                success=False,
                lobby=None,
                message=f"Failed to create lobby: {str(e)}"
            )
    
    async def join_lobby(self, device_id: str, code: str) -> LobbyResponse:
        """Join an existing lobby by code"""
        try:
            # Validate code format
            if not is_valid_lobby_code(code):
                return LobbyResponse(
                    success=False,
                    lobby=None,
                    message="Invalid lobby code format"
                )
            
            # Find lobby by code first
            lobby_result = self.supabase.table("lobbies")\
                .select("*")\
                .eq("code", code.upper())\
                .execute()
            
            if not lobby_result.data:
                return LobbyResponse(
                    success=False,
                    lobby=None,
                    message="Lobby not found"
                )
            
            lobby_data = lobby_result.data[0]
            target_lobby_id = lobby_data["id"]
            
            # Check if player is already in a lobby
            existing_member = self.supabase.table("lobby_members")\
                .select("lobby_id")\
                .eq("device_id", device_id)\
                .execute()
            
            if existing_member.data:
                current_lobby_id = existing_member.data[0]["lobby_id"]
                
                # Check if trying to join their own lobby
                if current_lobby_id == target_lobby_id:
                    return LobbyResponse(
                        success=False,
                        lobby=None,
                        message="You are already in this lobby"
                    )
                else:
                    # In a different lobby
                    return LobbyResponse(
                        success=False,
                        lobby=None,
                        message="You must leave your current lobby before joining another"
                    )
            
            lobby = LobbyDB(**lobby_data)
            
            # Check if lobby is full
            if lobby.current_players >= lobby.max_players:
                return LobbyResponse(
                    success=False,
                    lobby=None,
                    message="Lobby is full"
                )
            
            # Check if lobby is in correct state
            if lobby.status not in [LobbyStatus.WAITING, LobbyStatus.READY_CHECK]:
                return LobbyResponse(
                    success=False,
                    lobby=None,
                    message="Cannot join lobby in current state"
                )
            
            # Remove from matchmaking queue if present
            await self.matchmaking.leave_queue(device_id)
            
            # Add player to lobby
            member_data = {
                "lobby_id": lobby.id,
                "device_id": device_id,
                "is_ready": False,
                "joined_at": datetime.now().isoformat()
            }
            
            member_result = self.supabase.table("lobby_members")\
                .insert(member_data)\
                .execute()
            
            if not member_result.data:
                raise Exception("Failed to add player to lobby")
            
            # Update lobby player count
            new_player_count = lobby.current_players + 1
            self.supabase.table("lobbies")\
                .update({"current_players": new_player_count})\
                .eq("id", lobby.id)\
                .execute()
            
            # Get updated lobby with all members
            lobby_with_members = await self._get_lobby_with_members(lobby.id)
            
            log_lobby_event("lobby_joined", {
                "lobby_code": lobby.code,
                "joiner": device_id,
                "current_players": new_player_count
            }, device_id)
            
            return LobbyResponse(
                success=True,
                lobby=lobby_with_members.to_lobby_info(),
                message="Successfully joined lobby"
            )
            
        except Exception as e:
            log_lobby_event("lobby_join_error", {
                "device_id": device_id,
                "code": code,
                "error": str(e)
            }, device_id)
            
            return LobbyResponse(
                success=False,
                lobby=None,
                message=f"Failed to join lobby: {str(e)}"
            )
    
    async def leave_lobby(self, device_id: str) -> LobbyResponse:
        """Leave current lobby"""
        try:
            # Find player's lobby
            member_result = self.supabase.table("lobby_members")\
                .select("lobby_id")\
                .eq("device_id", device_id)\
                .execute()
            
            if not member_result.data:
                return LobbyResponse(
                    success=False,
                    lobby=None,
                    message="Player is not in any lobby"
                )
            
            lobby_id = member_result.data[0]["lobby_id"]
            
            # Get lobby info before removing player
            lobby_with_members = await self._get_lobby_with_members(lobby_id)
            
            # Remove player from lobby
            self.supabase.table("lobby_members")\
                .delete()\
                .eq("device_id", device_id)\
                .execute()
            
            # Update player count and check if lobby should be deleted
            new_player_count = lobby_with_members.lobby.current_players - 1
            
            if new_player_count == 0:
                # Delete empty lobby
                self.supabase.table("lobbies")\
                    .delete()\
                    .eq("id", lobby_id)\
                    .execute()
                
                log_lobby_event("lobby_deleted", {
                    "lobby_code": lobby_with_members.lobby.code,
                    "reason": "empty"
                }, device_id)
            else:
                # Update player count and reset ready states if countdown was active
                update_data = {"current_players": new_player_count}
                
                if lobby_with_members.lobby.status in [LobbyStatus.READY_CHECK, LobbyStatus.COUNTDOWN]:
                    update_data.update({
                        "status": LobbyStatus.WAITING.value,
                        "countdown_start_time": None
                    })
                    
                    # Reset all players to unready
                    self.supabase.table("lobby_members")\
                        .update({"is_ready": False})\
                        .eq("lobby_id", lobby_id)\
                        .execute()
                
                self.supabase.table("lobbies")\
                    .update(update_data)\
                    .eq("id", lobby_id)\
                    .execute()
            
            log_lobby_event("lobby_left", {
                "lobby_code": lobby_with_members.lobby.code,
                "leaver": device_id,
                "remaining_players": new_player_count
            }, device_id)
            
            return LobbyResponse(
                success=True,
                message="Successfully left lobby"
            )
            
        except Exception as e:
            log_lobby_event("lobby_leave_error", {
                "device_id": device_id,
                "error": str(e)
            }, device_id)
            
            return LobbyResponse(
                success=False,
                lobby=None,
                message=f"Failed to leave lobby: {str(e)}"
            )
    
    async def toggle_ready(self, device_id: str, is_ready: bool) -> LobbyResponse:
        """Toggle player's ready status"""
        try:
            # Find player's lobby membership
            member_result = self.supabase.table("lobby_members")\
                .select("*")\
                .eq("device_id", device_id)\
                .execute()
            
            if not member_result.data:
                return LobbyResponse(
                    success=False,
                    lobby=None,
                    message="Player is not in any lobby"
                )
            
            member_data = member_result.data[0]
            lobby_id = member_data["lobby_id"]
            
            # Update ready status
            self.supabase.table("lobby_members")\
                .update({"is_ready": is_ready})\
                .eq("device_id", device_id)\
                .execute()
            
            # Get updated lobby state
            lobby_with_members = await self._get_lobby_with_members(lobby_id)
            
            # Check if all players are ready
            all_ready = all(member.is_ready for member in lobby_with_members.members)
            is_full = lobby_with_members.lobby.current_players == lobby_with_members.lobby.max_players
            
            update_data = {}
            
            if all_ready and is_full and is_ready:
                # Start countdown
                update_data = {
                    "status": LobbyStatus.COUNTDOWN.value,
                    "countdown_start_time": datetime.now().isoformat()
                }
                
                log_lobby_event("countdown_started", {
                    "lobby_code": lobby_with_members.lobby.code
                })
                
            elif not all_ready and lobby_with_members.lobby.status == LobbyStatus.COUNTDOWN:
                # Abort countdown
                update_data = {
                    "status": LobbyStatus.READY_CHECK.value,
                    "countdown_start_time": None
                }
                
                log_lobby_event("countdown_aborted", {
                    "lobby_code": lobby_with_members.lobby.code,
                    "trigger_player": device_id
                })
            
            elif all_ready and is_full:
                update_data = {"status": LobbyStatus.READY_CHECK.value}
            else:
                update_data = {"status": LobbyStatus.WAITING.value}
            
            if update_data:
                self.supabase.table("lobbies")\
                    .update(update_data)\
                    .eq("id", lobby_id)\
                    .execute()
            
            # Get final lobby state
            final_lobby = await self._get_lobby_with_members(lobby_id)
            
            log_lobby_event("ready_toggle", {
                "lobby_code": final_lobby.lobby.code,
                "device_id": device_id,
                "is_ready": is_ready,
                "lobby_status": final_lobby.lobby.status
            }, device_id)
            
            return LobbyResponse(
                success=True,
                lobby=final_lobby.to_lobby_info(),
                message=f"Ready status updated to {is_ready}"
            )
            
        except Exception as e:
            log_lobby_event("ready_toggle_error", {
                "device_id": device_id,
                "is_ready": is_ready,
                "error": str(e)
            }, device_id)
            
            return LobbyResponse(
                success=False,
                lobby=None,
                message=f"Failed to update ready status: {str(e)}"
            )
    
    async def get_lobby_status(self, device_id: str) -> LobbyResponse:
        """Get current lobby status for a player"""
        try:
            # Find player's lobby
            member_result = self.supabase.table("lobby_members")\
                .select("lobby_id")\
                .eq("device_id", device_id)\
                .execute()
            
            if not member_result.data:
                return LobbyResponse(
                    success=True,
                    lobby=None,
                    message="Player is not in any lobby"
                )
            
            lobby_id = member_result.data[0]["lobby_id"]
            lobby_with_members = await self._get_lobby_with_members(lobby_id)
            
            return LobbyResponse(
                success=True,
                lobby=lobby_with_members.to_lobby_info(),
                message="Current lobby status"
            )
            
        except Exception as e:
            return LobbyResponse(
                success=False,
                lobby=None,
                message=f"Failed to get lobby status: {str(e)}"
            )
    
    async def _get_lobby_with_members(self, lobby_id: str) -> LobbyWithMembers:
        """Get lobby with all its members"""
        # Get lobby
        lobby_result = self.supabase.table("lobbies")\
            .select("*")\
            .eq("id", lobby_id)\
            .execute()
        
        if not lobby_result.data:
            raise Exception("Lobby not found")
        
        # Get members
        members_result = self.supabase.table("lobby_members")\
            .select("*")\
            .eq("lobby_id", lobby_id)\
            .execute()
        
        lobby = LobbyDB(**lobby_result.data[0])
        members = [LobbyMemberDB(**member) for member in members_result.data]
        
        return LobbyWithMembers(lobby=lobby, members=members)
    
    async def _generate_unique_code(self) -> str:
        """Generate a unique 4-character lobby code"""
        max_attempts = 10
        
        for _ in range(max_attempts):
            code = generate_lobby_code()
            
            existing = self.supabase.table("lobbies")\
                .select("code")\
                .eq("code", code)\
                .execute()
            
            if not existing.data:
                return code
        
        # Fallback
        base_code = generate_lobby_code()[:2]
        timestamp_suffix = str(int(datetime.now().timestamp()))[-2:]
        return base_code + timestamp_suffix

# Initialize service (will be set when integrating with main app)
lobby_service: Optional[LobbyService] = None

def init_lobby_service(supabase: Client):
    """Initialize lobby service with supabase client"""
    global lobby_service
    lobby_service = LobbyService(supabase)

def get_lobby_service() -> LobbyService:
    """Dependency to get lobby service"""
    if lobby_service is None:
        raise HTTPException(status_code=500, detail="Lobby service not initialized")
    return lobby_service

# Route endpoints
@lobby_router.post("/create", response_model=LobbyResponse)
async def create_lobby(
    request: CreateLobbyRequest,
    device_id: str = Depends(get_device_id),
    service: LobbyService = Depends(get_lobby_service)
):
    """Create a new lobby with a random 4-character code"""
    return await service.create_lobby(device_id)

@lobby_router.post("/join", response_model=LobbyResponse)
async def join_lobby(
    request: JoinLobbyRequest,
    device_id: str = Depends(get_device_id),
    service: LobbyService = Depends(get_lobby_service)
):
    """Join an existing lobby using its code"""
    return await service.join_lobby(device_id, request.code.upper())

@lobby_router.post("/leave", response_model=LobbyResponse)
async def leave_lobby(
    device_id: str = Depends(get_device_id),
    service: LobbyService = Depends(get_lobby_service)
):
    """Leave the current lobby"""
    return await service.leave_lobby(device_id)

@lobby_router.post("/ready", response_model=LobbyResponse)
async def toggle_ready(
    request: ReadyToggleRequest,
    device_id: str = Depends(get_device_id),
    service: LobbyService = Depends(get_lobby_service)
):
    """Toggle ready status in the current lobby"""
    return await service.toggle_ready(device_id, request.is_ready)

@lobby_router.get("/status", response_model=LobbyResponse)
async def get_lobby_status(
    device_id: str = Depends(get_device_id),
    service: LobbyService = Depends(get_lobby_service)
):
    """Get current lobby status"""
    return await service.get_lobby_status(device_id)

@lobby_router.post("/find_match", response_model=MatchmakingResponse)
async def find_match(
    request: FindMatchRequest,
    device_id: str = Depends(get_device_id),
    service: LobbyService = Depends(get_lobby_service)
):
    """Enter matchmaking queue or get matched with another player"""
    return await service.matchmaking.find_match(device_id)

@lobby_router.post("/leave_queue", response_model=dict)
async def leave_matchmaking_queue(
    device_id: str = Depends(get_device_id),
    service: LobbyService = Depends(get_lobby_service)
):
    """Leave the matchmaking queue"""
    success = await service.matchmaking.leave_queue(device_id)
    return {
        "success": success,
        "message": "Left matchmaking queue" if success else "Not in queue"
    }

@lobby_router.get("/queue_status", response_model=MatchmakingResponse)
async def get_queue_status(
    device_id: str = Depends(get_device_id),
    service: LobbyService = Depends(get_lobby_service)
):
    """Get current matchmaking queue status"""
    return await service.matchmaking.get_queue_status(device_id) 