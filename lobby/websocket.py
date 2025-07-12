import asyncio
import json
from typing import Dict, Set, Optional
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect, HTTPException
from supabase import Client

from .models import (
    WebSocketMessage, WebSocketEventType, LobbyStatus, LobbyDB, LobbyMemberDB,
    LobbyWithMembers, PlayerJoinedData, PlayerLeftData, ReadyStatusData,
    CountdownData, ErrorData
)
from .utils import (
    log_lobby_event, validate_device_id, is_countdown_active, 
    get_countdown_remaining
)

class ConnectionManager:
    """Manages WebSocket connections for lobby system"""
    
    def __init__(self):
        # lobby_code -> {device_id -> websocket}
        self.active_connections: Dict[str, Dict[str, WebSocket]] = {}
        # device_id -> lobby_code mapping for quick lookup
        self.device_to_lobby: Dict[str, str] = {}
        # Background tasks for countdown management
        self.countdown_tasks: Dict[str, asyncio.Task] = {}
    
    async def connect(self, websocket: WebSocket, lobby_code: str, device_id: str):
        """Accept WebSocket connection and register it"""
        await websocket.accept()
        
        if lobby_code not in self.active_connections:
            self.active_connections[lobby_code] = {}
        
        # Store connection
        self.active_connections[lobby_code][device_id] = websocket
        self.device_to_lobby[device_id] = lobby_code
        
        log_lobby_event("websocket_connected", {
            "lobby_code": lobby_code,
            "device_id": device_id,
            "total_connections": len(self.active_connections[lobby_code])
        }, device_id)
    
    def disconnect(self, lobby_code: str, device_id: str):
        """Remove WebSocket connection"""
        if lobby_code in self.active_connections:
            if device_id in self.active_connections[lobby_code]:
                del self.active_connections[lobby_code][device_id]
                
                # Clean up empty lobby connections
                if not self.active_connections[lobby_code]:
                    del self.active_connections[lobby_code]
                    # Cancel countdown task if exists
                    if lobby_code in self.countdown_tasks:
                        self.countdown_tasks[lobby_code].cancel()
                        del self.countdown_tasks[lobby_code]
        
        if device_id in self.device_to_lobby:
            del self.device_to_lobby[device_id]
        
        log_lobby_event("websocket_disconnected", {
            "lobby_code": lobby_code,
            "device_id": device_id
        }, device_id)
    
    async def send_personal_message(self, message: dict, lobby_code: str, device_id: str):
        """Send message to specific player"""
        if (lobby_code in self.active_connections and 
            device_id in self.active_connections[lobby_code]):
            
            websocket = self.active_connections[lobby_code][device_id]
            try:
                await websocket.send_text(json.dumps(message, default=str))
            except Exception as e:
                log_lobby_event("websocket_send_error", {
                    "lobby_code": lobby_code,
                    "device_id": device_id,
                    "error": str(e)
                })
                # Remove broken connection
                self.disconnect(lobby_code, device_id)
    
    async def broadcast_to_lobby(self, message: dict, lobby_code: str, exclude_device: Optional[str] = None):
        """Broadcast message to all players in a lobby"""
        
        # 🔍 CRITICAL DEBUG
        log_lobby_event("broadcast_attempt", {
            "lobby_code": lobby_code,
            "message_type": message.get("type", "unknown"),
            "all_active_lobbies": list(self.active_connections.keys()),
            "lobby_exists": lobby_code in self.active_connections,
            "exclude_device": exclude_device
        })
        
        if lobby_code not in self.active_connections:
            log_lobby_event("broadcast_failed_no_lobby", {
                "lobby_code": lobby_code,
                "message_type": message.get("type", "unknown"),
                "active_lobbies": list(self.active_connections.keys())
            })
            return
        
        connections = self.active_connections[lobby_code].copy()
        
        # 🔍 DEBUG: Connection details
        log_lobby_event("broadcast_connections_found", {
            "lobby_code": lobby_code,
            "message_type": message.get("type", "unknown"),
            "total_connections": len(connections),
            "device_ids": list(connections.keys())
        })
        
        successful_sends = 0
        for device_id, websocket in connections.items():
            if exclude_device and device_id == exclude_device:
                log_lobby_event("broadcast_excluded", {
                    "lobby_code": lobby_code,
                    "excluded_device": device_id
                })
                continue
                
            try:
                await websocket.send_text(json.dumps(message, default=str))
                successful_sends += 1
                log_lobby_event("broadcast_sent_success", {
                    "lobby_code": lobby_code,
                    "device_id": device_id,
                    "message_type": message.get("type", "unknown")
                })
            except Exception as e:
                log_lobby_event("websocket_broadcast_error", {
                    "lobby_code": lobby_code,
                    "device_id": device_id,
                    "error": str(e),
                    "message_type": message.get("type", "unknown")
                })
                # Remove broken connection
                self.disconnect(lobby_code, device_id)
        
        # 🔍 Final broadcast summary
        log_lobby_event("broadcast_summary", {
            "lobby_code": lobby_code,
            "message_type": message.get("type", "unknown"),
            "successful_sends": successful_sends,
            "total_attempts": len(connections)
        })
    
    def get_lobby_connection_count(self, lobby_code: str) -> int:
        """Get number of active connections for a lobby"""
        return len(self.active_connections.get(lobby_code, {}))
    
    def is_player_connected(self, lobby_code: str, device_id: str) -> bool:
        """Check if a player is connected to lobby WebSocket"""
        return (lobby_code in self.active_connections and 
                device_id in self.active_connections[lobby_code])
    
    async def start_countdown_task(self, lobby_code: str, supabase: Client):
        """Start countdown task for a lobby"""
        # Cancel existing countdown if any
        if lobby_code in self.countdown_tasks:
            self.countdown_tasks[lobby_code].cancel()
        
        # Start new countdown task
        task = asyncio.create_task(self._countdown_worker(lobby_code, supabase))
        self.countdown_tasks[lobby_code] = task
    
    async def stop_countdown_task(self, lobby_code: str):
        """Stop countdown task for a lobby"""
        if lobby_code in self.countdown_tasks:
            self.countdown_tasks[lobby_code].cancel()
            del self.countdown_tasks[lobby_code]
    
    async def _countdown_worker(self, lobby_code: str, supabase: Client):
        """Background worker for countdown management"""
        try:
            for remaining in range(3, -1, -1):
                # Broadcast countdown tick
                message = WebSocketMessage(
                    type=WebSocketEventType.COUNTDOWN_TICK,
                    data={"seconds_remaining": remaining}
                ).dict()
                
                await self.broadcast_to_lobby(message, lobby_code)
                
                log_lobby_event("countdown_tick", {
                    "lobby_code": lobby_code,
                    "seconds_remaining": remaining
                })
                
                if remaining > 0:
                    await asyncio.sleep(1)
            
            # Countdown finished - start game
            await self._handle_game_start(lobby_code, supabase)
            
        except asyncio.CancelledError:
            log_lobby_event("countdown_cancelled", {
                "lobby_code": lobby_code
            })
        except Exception as e:
            log_lobby_event("countdown_error", {
                "lobby_code": lobby_code,
                "error": str(e)
            })
    
    async def _handle_game_start(self, lobby_code: str, supabase: Client):
        """Handle game start and lobby cleanup"""
        try:
            # Update lobby status to game_started
            supabase.table("lobbies")\
                .update({"status": LobbyStatus.GAME_STARTED.value})\
                .eq("code", lobby_code)\
                .execute()
            
            # Broadcast game start event
            message = WebSocketMessage(
                type=WebSocketEventType.GAME_STARTED,
                data={"lobby_code": lobby_code}
            ).dict()
            
            await self.broadcast_to_lobby(message, lobby_code)
            
            log_lobby_event("game_started", {
                "lobby_code": lobby_code
            })
            
            # Clean up lobby after a short delay
            await asyncio.sleep(2)
            
            # Delete lobby from database
            supabase.table("lobbies")\
                .delete()\
                .eq("code", lobby_code)\
                .execute()
            
            # Broadcast lobby deleted event
            delete_message = WebSocketMessage(
                type=WebSocketEventType.LOBBY_DELETED,
                data={"reason": "game_started"}
            ).dict()
            
            await self.broadcast_to_lobby(delete_message, lobby_code)
            
            log_lobby_event("lobby_deleted", {
                "lobby_code": lobby_code,
                "reason": "game_started"
            })
            
            # Clean up connections
            if lobby_code in self.active_connections:
                # Close all connections
                for device_id, websocket in self.active_connections[lobby_code].items():
                    try:
                        await websocket.close()
                    except:
                        pass
                
                del self.active_connections[lobby_code]
            
            # Remove countdown task
            if lobby_code in self.countdown_tasks:
                del self.countdown_tasks[lobby_code]
            
        except Exception as e:
            log_lobby_event("game_start_error", {
                "lobby_code": lobby_code,
                "error": str(e)
            })

# Global connection manager
manager = ConnectionManager()

# Initialize handler
websocket_handler = None

def init_websocket_handler(supabase: Client):
    """Initialize WebSocket handler with supabase client"""
    global websocket_handler
    websocket_handler = LobbyWebSocketHandler(supabase)

def get_websocket_handler():
    """Get WebSocket handler instance"""
    if websocket_handler is None:
        raise HTTPException(status_code=500, detail="WebSocket handler not initialized")
    return websocket_handler

class LobbyWebSocketHandler:
    """WebSocket handler for lobby events"""
    
    def __init__(self, supabase: Client):
        self.supabase = supabase
    
    async def handle_connection(self, websocket: WebSocket, lobby_code: str, device_id: str):
        """Handle new WebSocket connection"""
        
        # Validate device_id
        if not validate_device_id(device_id):
            await websocket.close(code=4001, reason="Invalid device_id")
            return
        
        # Validate lobby exists and player is member
        lobby_check = await self._validate_lobby_membership(lobby_code, device_id)
        if not lobby_check:
            await websocket.close(code=4004, reason="Not a member of this lobby")
            return
        
        try:
            # Connect to lobby
            await manager.connect(websocket, lobby_code, device_id)
            
            # Send initial lobby state
            await self._send_lobby_state(lobby_code, device_id)
            
            # Start countdown if needed
            await self._check_and_start_countdown(lobby_code)
            
            # Listen for disconnection
            try:
                while True:
                    # Keep connection alive - in a real app you might want to handle incoming messages here
                    await websocket.receive_text()
                    
            except WebSocketDisconnect:
                pass
                
        except Exception as e:
            log_lobby_event("websocket_error", {
                "lobby_code": lobby_code,
                "device_id": device_id,
                "error": str(e)
            })
        finally:
            # Handle disconnection
            await self._handle_disconnection(lobby_code, device_id)
    
    async def _validate_lobby_membership(self, lobby_code: str, device_id: str) -> bool:
        """Validate that player is a member of the lobby"""
        try:
            # Check if lobby exists and player is a member
            result = self.supabase.table("lobby_members")\
                .select("lobby_id")\
                .eq("device_id", device_id)\
                .execute()
            
            if not result.data:
                return False
            
            # Get lobby info
            lobby_result = self.supabase.table("lobbies")\
                .select("code")\
                .eq("id", result.data[0]["lobby_id"])\
                .execute()
            
            if not lobby_result.data:
                return False
            
            return lobby_result.data[0]["code"] == lobby_code.upper()
            
        except Exception:
            return False
    
    async def _send_lobby_state(self, lobby_code: str, device_id: str):
        """Send current lobby state to connected player"""
        try:
            lobby_with_members = await self._get_lobby_with_members(lobby_code)
            if lobby_with_members:
                
                # Get player data for usernames
                device_ids = [member.device_id for member in lobby_with_members.members]
                players_data = {}
                
                if device_ids:
                    players_result = self.supabase.table("players")\
                        .select("device_id, user_name")\
                        .in_("device_id", device_ids)\
                        .execute()
                    
                    if players_result.data:
                        players_data = {p["device_id"]: p for p in players_result.data}
                
                lobby_info = lobby_with_members.to_lobby_info(players_data)
                
                message = WebSocketMessage(
                    type=WebSocketEventType.PLAYER_JOINED,
                    data={"lobby": lobby_info.dict()}
                ).dict()
                
                await manager.send_personal_message(message, lobby_code, device_id)
                
        except Exception as e:
            log_lobby_event("send_lobby_state_error", {
                "lobby_code": lobby_code,
                "device_id": device_id,
                "error": str(e)
            })
    
    async def _check_and_start_countdown(self, lobby_code: str):
        """Check if countdown should be running and start it if needed"""
        try:
            lobby_result = self.supabase.table("lobbies")\
                .select("*")\
                .eq("code", lobby_code)\
                .execute()
            
            if lobby_result.data:
                lobby_data = lobby_result.data[0]
                
                if (lobby_data["status"] == LobbyStatus.COUNTDOWN.value and 
                    lobby_data["countdown_start_time"]):
                    
                    countdown_start = datetime.fromisoformat(lobby_data["countdown_start_time"].replace('Z', '+00:00'))
                    
                    if is_countdown_active(countdown_start):
                        await manager.start_countdown_task(lobby_code, self.supabase)
                        
        except Exception as e:
            log_lobby_event("countdown_check_error", {
                "lobby_code": lobby_code,
                "error": str(e)
            })
    
    async def _handle_disconnection(self, lobby_code: str, device_id: str):
        """Handle player disconnection"""
        try:
            # Remove from manager
            manager.disconnect(lobby_code, device_id)
            
            # Check if player should be removed from lobby (auto-leave on disconnect)
            # This follows the requirement that disconnection = automatic removal
            
            # Get lobby info
            member_result = self.supabase.table("lobby_members")\
                .select("lobby_id")\
                .eq("device_id", device_id)\
                .execute()
            
            if member_result.data:
                lobby_id = member_result.data[0]["lobby_id"]
                
                # Get lobby before removing player
                lobby_with_members = await self._get_lobby_with_members_by_id(lobby_id)
                
                if lobby_with_members:
                    # Remove player from lobby
                    self.supabase.table("lobby_members")\
                        .delete()\
                        .eq("device_id", device_id)\
                        .execute()
                    
                    new_player_count = lobby_with_members.lobby.current_players - 1
                    
                    if new_player_count == 0:
                        # Delete empty lobby
                        self.supabase.table("lobbies")\
                            .delete()\
                            .eq("id", lobby_id)\
                            .execute()
                        
                        # Stop countdown if running
                        await manager.stop_countdown_task(lobby_code)
                        
                        log_lobby_event("lobby_deleted", {
                            "lobby_code": lobby_code,
                            "reason": "disconnection_empty"
                        }, device_id)
                        
                    else:
                        # Update lobby and potentially abort countdown
                        update_data = {"current_players": new_player_count}
                        
                        if lobby_with_members.lobby.status in [LobbyStatus.READY_CHECK, LobbyStatus.COUNTDOWN]:
                            update_data.update({
                                "status": LobbyStatus.WAITING.value,
                                "countdown_start_time": None
                            })
                            
                            # Reset remaining players to unready
                            self.supabase.table("lobby_members")\
                                .update({"is_ready": False})\
                                .eq("lobby_id", lobby_id)\
                                .execute()
                            
                            # Stop countdown
                            await manager.stop_countdown_task(lobby_code)
                        
                        self.supabase.table("lobbies")\
                            .update(update_data)\
                            .eq("id", lobby_id)\
                            .execute()
                        
                        # Broadcast player left event
                        updated_lobby = await self._get_lobby_with_members_by_id(lobby_id)
                        if updated_lobby:
                            # Get player data
                            device_ids = [member.device_id for member in updated_lobby.members]
                            players_data = {}
                            
                            if device_ids:
                                players_result = self.supabase.table("players")\
                                    .select("device_id, user_name")\
                                    .in_("device_id", device_ids)\
                                    .execute()
                                
                                if players_result.data:
                                    players_data = {p["device_id"]: p for p in players_result.data}
                            
                            lobby_info = updated_lobby.to_lobby_info(players_data)
                            
                            message = WebSocketMessage(
                                type=WebSocketEventType.PLAYER_LEFT,
                                data={
                                    "device_id": device_id,
                                    "lobby": lobby_info.dict()
                                }
                            ).dict()
                            
                            await manager.broadcast_to_lobby(message, lobby_code)
                    
                    log_lobby_event("lobby_left_on_disconnect", {
                        "lobby_code": lobby_code,
                        "device_id": device_id,
                        "remaining_players": new_player_count
                    }, device_id)
                    
        except Exception as e:
            log_lobby_event("disconnection_error", {
                "lobby_code": lobby_code,
                "device_id": device_id,
                "error": str(e)
            })
    
    async def _get_lobby_with_members(self, lobby_code: str):
        """Get lobby by code with all members"""
        try:
            # Get lobby
            lobby_result = self.supabase.table("lobbies")\
                .select("*")\
                .eq("code", lobby_code.upper())\
                .execute()
            
            if not lobby_result.data:
                return None
            
            lobby_id = lobby_result.data[0]["id"]
            return await self._get_lobby_with_members_by_id(lobby_id)
            
        except Exception:
            return None
    
    async def _get_lobby_with_members_by_id(self, lobby_id: str):
        """Get lobby by ID with all members"""
        try:
            # Get lobby
            lobby_result = self.supabase.table("lobbies")\
                .select("*")\
                .eq("id", lobby_id)\
                .execute()
            
            if not lobby_result.data:
                return None
            
            # Get members
            members_result = self.supabase.table("lobby_members")\
                .select("*")\
                .eq("lobby_id", lobby_id)\
                .execute()
            
            lobby = LobbyDB(**lobby_result.data[0])
            members = [LobbyMemberDB(**member) for member in members_result.data]
            
            return LobbyWithMembers(lobby=lobby, members=members)
            
        except Exception:
            return None

# Event broadcasting functions for use in routes
async def broadcast_player_joined(lobby_code: str, lobby_info: dict):
    """Broadcast player joined event"""
    message = WebSocketMessage(
        type=WebSocketEventType.PLAYER_JOINED,
        data={"lobby": lobby_info}
    ).dict()
    
    await manager.broadcast_to_lobby(message, lobby_code)

async def broadcast_player_left(lobby_code: str, device_id: str, lobby_info: dict):
    """Broadcast player left event"""
    message = WebSocketMessage(
        type=WebSocketEventType.PLAYER_LEFT,
        data={
            "device_id": device_id,
            "lobby": lobby_info
        }
    ).dict()
    
    await manager.broadcast_to_lobby(message, lobby_code)

async def broadcast_ready_status_changed(lobby_code: str, device_id: str, is_ready: bool, lobby_info: dict):
    """Broadcast ready status change event"""
    
    # 🔍 CRITICAL DEBUG
    log_lobby_event("ready_broadcast_called", {
        "lobby_code": lobby_code,
        "device_id": device_id,
        "is_ready": is_ready,
        "active_lobbies": list(manager.active_connections.keys()),
        "lobby_exists_in_manager": lobby_code in manager.active_connections
    })
    
    message = WebSocketMessage(
        type=WebSocketEventType.READY_STATUS_CHANGED,
        data={
            "device_id": device_id,
            "is_ready": is_ready,
            "lobby": lobby_info
        }
    ).dict()
    
    # 🔍 DEBUG: Log the message being sent
    log_lobby_event("ready_broadcast_message", {
        "lobby_code": lobby_code,
        "message_type": message["type"],
        "message_data_keys": list(message["data"].keys())
    })
    
    await manager.broadcast_to_lobby(message, lobby_code)
    
    # 🔍 DEBUG: Log after broadcast attempt
    log_lobby_event("ready_broadcast_completed", {
        "lobby_code": lobby_code,
        "device_id": device_id
    })

async def broadcast_countdown_started(lobby_code: str, lobby_info: dict):
    """Broadcast countdown started event and start countdown task"""
    message = WebSocketMessage(
        type=WebSocketEventType.COUNTDOWN_STARTED,
        data={"lobby": lobby_info}
    ).dict()
    
    await manager.broadcast_to_lobby(message, lobby_code)

async def broadcast_countdown_aborted(lobby_code: str, lobby_info: dict):
    """Broadcast countdown aborted event and stop countdown task"""
    message = WebSocketMessage(
        type=WebSocketEventType.COUNTDOWN_ABORTED,
        data={"lobby": lobby_info}
    ).dict()
    
    await manager.broadcast_to_lobby(message, lobby_code)
    await manager.stop_countdown_task(lobby_code) 