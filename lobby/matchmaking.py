from typing import Optional, Tuple
from datetime import datetime
from supabase import Client
from .models import (
    MatchmakingQueueDB, LobbyDB, LobbyMemberDB, LobbyStatus, 
    MatchmakingResponse, LobbyWithMembers
)
from .utils import generate_lobby_code, log_lobby_event, calculate_estimated_wait_time

class MatchmakingService:
    """Handles automatic matchmaking with FIFO queue"""
    
    def __init__(self, supabase: Client):
        self.supabase = supabase
    
    async def find_match(self, device_id: str) -> MatchmakingResponse:
        """
        Add player to matchmaking queue or match them with existing player
        
        Returns:
            MatchmakingResponse with queue status or created lobby
        """
        try:
            # Check if player is already in a lobby
            existing_member = self.supabase.table("lobby_members")\
                .select("lobby_id")\
                .eq("device_id", device_id)\
                .execute()
            
            if existing_member.data:
                return MatchmakingResponse(
                    success=False,
                    in_queue=False,
                    message="You must leave your current lobby before entering matchmaking"
                )
            
            # Check if player is already in queue
            existing_queue = self.supabase.table("matchmaking_queue")\
                .select("*")\
                .eq("device_id", device_id)\
                .execute()
            
            if existing_queue.data:
                # Player already in queue, return queue status
                return await self._get_queue_status(device_id)
            
            # Check if there's someone waiting in queue
            waiting_players = self.supabase.table("matchmaking_queue")\
                .select("*")\
                .order("queue_time", desc=False)\
                .limit(1)\
                .execute()
            
            if waiting_players.data:
                # Match found! Create lobby with both players
                opponent_device_id = waiting_players.data[0]["device_id"]
                
                # Remove opponent from queue
                self.supabase.table("matchmaking_queue")\
                    .delete()\
                    .eq("device_id", opponent_device_id)\
                    .execute()
                
                # Create lobby
                lobby = await self._create_matchmaking_lobby(device_id, opponent_device_id)
                
                log_lobby_event("matchmaking_match_found", {
                    "lobby_code": lobby.lobby.code,
                    "player1": device_id,
                    "player2": opponent_device_id
                })
                
                return MatchmakingResponse(
                    success=True,
                    in_queue=False,
                    message="Match found! Lobby created.",
                    lobby=lobby.to_lobby_info()
                )
            
            else:
                # No one waiting, add to queue
                self.supabase.table("matchmaking_queue")\
                    .insert({
                        "device_id": device_id,
                        "queue_time": datetime.now().isoformat()
                    })\
                    .execute()
                
                log_lobby_event("matchmaking_queue_join", {
                    "device_id": device_id
                })
                
                return MatchmakingResponse(
                    success=True,
                    in_queue=True,
                    estimated_wait_time=30,  # Base wait time for first in queue
                    queue_position=1,
                    message="Added to matchmaking queue. Waiting for opponent..."
                )
                
        except Exception as e:
            log_lobby_event("matchmaking_error", {
                "device_id": device_id,
                "error": str(e)
            })
            
            return MatchmakingResponse(
                success=False,
                in_queue=False,
                message=f"Matchmaking error: {str(e)}"
            )
    
    async def leave_queue(self, device_id: str) -> bool:
        """
        Remove player from matchmaking queue
        
        Returns:
            True if successfully removed, False if not in queue
        """
        try:
            result = self.supabase.table("matchmaking_queue")\
                .delete()\
                .eq("device_id", device_id)\
                .execute()
            
            if result.data:
                log_lobby_event("matchmaking_queue_leave", {
                    "device_id": device_id
                })
                return True
            
            return False
            
        except Exception as e:
            log_lobby_event("matchmaking_leave_error", {
                "device_id": device_id,
                "error": str(e)
            })
            return False
    
    async def get_queue_status(self, device_id: str) -> Optional[MatchmakingResponse]:
        """Get current queue status for a player"""
        return await self._get_queue_status(device_id)
    
    async def _get_queue_status(self, device_id: str) -> Optional[MatchmakingResponse]:
        """Internal method to get queue status"""
        try:
            # Get all queue entries ordered by time
            all_queue = self.supabase.table("matchmaking_queue")\
                .select("*")\
                .order("queue_time", desc=False)\
                .execute()
            
            if not all_queue.data:
                return MatchmakingResponse(
                    success=True,
                    in_queue=False,
                    message="Not in queue"
                )
            
            # Find player's position
            for i, entry in enumerate(all_queue.data, 1):
                if entry["device_id"] == device_id:
                    wait_time = calculate_estimated_wait_time(i)
                    
                    return MatchmakingResponse(
                        success=True,
                        in_queue=True,
                        estimated_wait_time=wait_time,
                        queue_position=i,
                        message=f"In queue (position {i}/{len(all_queue.data)})"
                    )
            
            return MatchmakingResponse(
                success=True,
                in_queue=False,
                message="Not in queue"
            )
            
        except Exception as e:
            return MatchmakingResponse(
                success=False,
                in_queue=False,
                message=f"Error checking queue status: {str(e)}"
            )
    
    async def _create_matchmaking_lobby(self, player1_id: str, player2_id: str) -> LobbyWithMembers:
        """Create a lobby for two matched players"""
        
        # Generate unique lobby code
        code = await self._generate_unique_code()
        
        # Create lobby
        lobby_data = {
            "code": code,
            "status": LobbyStatus.WAITING.value,
            "max_players": 2,
            "current_players": 2,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        
        lobby_result = self.supabase.table("lobbies")\
            .insert(lobby_data)\
            .execute()
        
        if not lobby_result.data:
            raise Exception("Failed to create lobby")
        
        lobby_id = lobby_result.data[0]["id"]
        
        # Add both players to lobby
        members_data = [
            {
                "lobby_id": lobby_id,
                "device_id": player1_id,
                "is_ready": False,
                "joined_at": datetime.now().isoformat()
            },
            {
                "lobby_id": lobby_id,
                "device_id": player2_id,
                "is_ready": False,
                "joined_at": datetime.now().isoformat()
            }
        ]
        
        members_result = self.supabase.table("lobby_members")\
            .insert(members_data)\
            .execute()
        
        if not members_result.data:
            # Cleanup lobby if member creation fails
            self.supabase.table("lobbies").delete().eq("id", lobby_id).execute()
            raise Exception("Failed to add players to lobby")
        
        # Return lobby with members
        lobby = LobbyDB(**lobby_result.data[0])
        members = [LobbyMemberDB(**member) for member in members_result.data]
        
        return LobbyWithMembers(lobby=lobby, members=members)
    
    async def _generate_unique_code(self) -> str:
        """Generate a unique 4-character lobby code"""
        max_attempts = 10
        
        for _ in range(max_attempts):
            code = generate_lobby_code()
            
            # Check if code exists
            existing = self.supabase.table("lobbies")\
                .select("code")\
                .eq("code", code)\
                .execute()
            
            if not existing.data:
                return code
        
        # Fallback: append timestamp if all random codes are taken
        base_code = generate_lobby_code()[:2]
        timestamp_suffix = str(int(datetime.now().timestamp()))[-2:]
        return base_code + timestamp_suffix
    
    async def cleanup_expired_queue_entries(self, max_age_hours: int = 1):
        """Clean up old queue entries (optional maintenance function)"""
        try:
            cutoff_time = datetime.now().replace(
                hour=datetime.now().hour - max_age_hours
            ).isoformat()
            
            result = self.supabase.table("matchmaking_queue")\
                .delete()\
                .lt("queue_time", cutoff_time)\
                .execute()
            
            if result.data:
                log_lobby_event("matchmaking_queue_cleanup", {
                    "removed_entries": len(result.data),
                    "cutoff_time": cutoff_time
                })
            
        except Exception as e:
            log_lobby_event("matchmaking_cleanup_error", {
                "error": str(e)
            }) 