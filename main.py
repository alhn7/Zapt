#dev test
from fastapi import FastAPI, HTTPException, WebSocket
from pydantic import BaseModel, Field
import uvicorn
from datetime import datetime
import platform
import socket
from supabase import create_client, Client
import os
from typing import List, Optional

# Lobby system imports
from lobby.routes import lobby_router, init_lobby_service
from lobby.websocket import init_websocket_handler, get_websocket_handler
from lobby.utils import log_lobby_event

# Supabase configuration
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://bvmeayqagxnxndwnacjr.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJ2bWVheXFhZ3hueG5kd25hY2pyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTA1Nzg3NjEsImV4cCI6MjA2NjE1NDc2MX0.Xm9OI7pUJI5Ua7QtVSGqHPfLDM6tuqSsUYG4KDduyXA")

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Create FastAPI instance
app = FastAPI(
    title="Player Authentication & Lobby API",
    description="A FastAPI application with Supabase for player authentication and 1v1 lobby system",
    version="1.0.0"
)

# Initialize lobby system
init_lobby_service(supabase)
init_websocket_handler(supabase)

# Include lobby routes
app.include_router(lobby_router)

# Request Models
class CreatePlayerRequest(BaseModel):
    device_id: str = Field(..., description="Unique device identifier")

class LoginRequest(BaseModel):
    device_id: str = Field(..., description="Device ID for login")

class UpdateUsernameRequest(BaseModel):
    username: str = Field(..., max_length=16, description="Username (max 16 characters)")

# Response Models
class PlayerData(BaseModel):
    device_id: str
    user_name: Optional[str] = None
    available_ability_ids: List[int] = []
    gold: int = 0
    diamond: int = 0
    elo: int = 1000
    last_online: datetime
    created_at: datetime
    updated_at: datetime

class PlayerResponse(BaseModel):
    exists: bool
    player: Optional[PlayerData] = None

class LoginResponse(BaseModel):
    exists: bool
    player: Optional[PlayerData] = None
    needs_username: bool = False

class HealthResponse(BaseModel):
    status: str
    message: str
    timestamp: str
    host_info: dict

class ErrorResponse(BaseModel):
    error: str
    message: str

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint - basic welcome message"""
    return {
        "message": "Player Authentication API is running!",
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    }

# Health check endpoint - Optimized for Render.com
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint optimized for Render.com
    - Returns 200 status code for healthy service
    - Responds quickly (well under 5 seconds)
    - Provides essential service information
    """
    try:
        # Get basic host information quickly
        hostname = socket.gethostname()
        # Use a faster method to get IP that doesn't require DNS lookup
        try:
            host_ip = socket.gethostbyname(hostname)
        except:
            host_ip = "127.0.0.1"  # Fallback to localhost
        
        return HealthResponse(
            status="healthy",
            message="Service is healthy and ready to receive traffic",
            timestamp=datetime.now().isoformat(),
            host_info={
                "hostname": hostname,
                "ip_address": host_ip,
                "platform": platform.system(),
                "platform_release": platform.release(),
                "architecture": platform.machine(),
                "processor": platform.processor()
            }
        )
    except Exception as e:
        # If anything fails, still return a 200 but indicate potential issues
        return HealthResponse(
            status="degraded",
            message=f"Service is running but with reduced functionality: {str(e)}",
            timestamp=datetime.now().isoformat(),
            host_info={
                "hostname": "unknown",
                "ip_address": "unknown",
                "platform": platform.system(),
                "platform_release": "unknown",
                "architecture": "unknown",
                "processor": "unknown"
            }
        )

# Player Management Endpoints

@app.post("/players", response_model=PlayerData)
async def create_player(request: CreatePlayerRequest):
    """Create a new player with device ID"""
    try:
        # Check if player already exists
        existing_player = supabase.table("players").select("device_id").eq("device_id", request.device_id).execute()
        
        if existing_player.data:
            raise HTTPException(
                status_code=400,
                detail={"error": "userAlreadyExist", "message": "Player with this device ID already exists"}
            )
        
        # Create new player
        now = datetime.now().isoformat()
        new_player_data = {
            "device_id": request.device_id,
            "user_name": None,
            "available_ability_ids": [],
            "gold": 0,
            "diamond": 0,
            "elo": 1000,
            "last_online": now,
            "created_at": now,
            "updated_at": now
        }
        
        result = supabase.table("players").insert(new_player_data).execute()
        
        if not result.data:
            raise HTTPException(status_code=500, detail={"error": "creationFailed", "message": "Failed to create player"})
        
        return PlayerData(**result.data[0])
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "internalError", "message": str(e)})

@app.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """Login endpoint - checks if player exists and updates last_online"""
    try:
        # Get player data
        result = supabase.table("players").select("*").eq("device_id", request.device_id).execute()
        
        if not result.data:
            raise HTTPException(
                status_code=404,
                detail={"error": "userDoNotHaveAccount", "message": "User should create account first"}
            )
        
        player_data = result.data[0]
        
        # Update last_online
        supabase.table("players").update({
            "last_online": datetime.now().isoformat()
        }).eq("device_id", request.device_id).execute()
        
        # Check if username is needed
        needs_username = player_data["user_name"] is None or player_data["user_name"].strip() == ""
        
        return LoginResponse(
            exists=True,
            player=PlayerData(**player_data),
            needs_username=needs_username
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "internalError", "message": str(e)})

@app.put("/players/{device_id}/username", response_model=PlayerData)
async def update_username(device_id: str, request: UpdateUsernameRequest):
    """Update player username"""
    try:
        # Check if player exists
        player_result = supabase.table("players").select("device_id").eq("device_id", device_id).execute()
        
        if not player_result.data:
            raise HTTPException(status_code=404, detail={"error": "playerNotFound", "message": "Player not found"})
        
        # Check if username is already taken by another player
        username_check = supabase.table("players").select("device_id").eq("user_name", request.username).neq("device_id", device_id).execute()
        
        if username_check.data:
            raise HTTPException(
                status_code=400,
                detail={"error": "usernameAlreadyExist", "message": "Username is already taken"}
            )
        
        # Update username
        update_result = supabase.table("players").update({
            "user_name": request.username,
            "updated_at": datetime.now().isoformat()
        }).eq("device_id", device_id).execute()
        
        if not update_result.data:
            raise HTTPException(status_code=500, detail={"error": "updateFailed", "message": "Failed to update username"})
        
        # Get the updated player data
        result = supabase.table("players").select("*").eq("device_id", device_id).execute()
        
        return PlayerData(**result.data[0])
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "internalError", "message": str(e)})

@app.get("/players/{device_id}", response_model=PlayerResponse)
async def get_player(device_id: str):
    """Get player data and update last_online"""
    try:
        # Get player data
        result = supabase.table("players").select("*").eq("device_id", device_id).execute()
        
        if not result.data:
            return PlayerResponse(exists=False, player=None)
        
        # Update last_online
        supabase.table("players").update({
            "last_online": datetime.now().isoformat()
        }).eq("device_id", device_id).execute()
        
        return PlayerResponse(
            exists=True,
            player=PlayerData(**result.data[0])
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "internalError", "message": str(e)})

@app.delete("/players/{device_id}")
async def delete_player(device_id: str):
    """Delete player account"""
    try:
        # Check if player exists
        player_result = supabase.table("players").select("device_id").eq("device_id", device_id).execute()
        
        if not player_result.data:
            raise HTTPException(status_code=404, detail={"error": "playerNotFound", "message": "Player not found"})
        
        # Delete player
        result = supabase.table("players").delete().eq("device_id", device_id).execute()
        
        return {"success": True, "message": "Player deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "internalError", "message": str(e)})

# Development Endpoints - For debugging and data inspection

@app.get("/dev/tables", tags=["Development"])
async def list_all_tables():
    """Development endpoint - List all database tables"""
    try:
        # For now, return the known tables. In future, you can add more tables here
        tables = ["players"]  # Add more table names as you create them
        
        return {
            "tables": [{"name": table, "schema": "public"} for table in tables],
            "count": len(tables),
            "note": "Manually maintained list - add new tables to this endpoint as needed"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "internalError", "message": str(e)})

@app.get("/dev/players", tags=["Development"])
async def view_all_players():
    """Development endpoint - View all players in the database"""
    try:
        result = supabase.table("players").select("*").execute()
        
        return {
            "table": "players",
            "count": len(result.data) if result.data else 0,
            "data": result.data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "internalError", "message": str(e)})

@app.get("/dev/players/stats", tags=["Development"])
async def players_statistics():
    """Development endpoint - Get players table statistics"""
    try:
        # Get basic counts and stats
        all_players = supabase.table("players").select("*").execute()
        
        if not all_players.data:
            return {
                "table": "players",
                "total_players": 0,
                "players_with_username": 0,
                "players_without_username": 0,
                "average_gold": 0,
                "average_diamond": 0,
                "average_elo": 0
            }
        
        players = all_players.data
        with_username = len([p for p in players if p.get("user_name")])
        without_username = len(players) - with_username
        
        avg_gold = sum(p.get("gold", 0) for p in players) / len(players)
        avg_diamond = sum(p.get("diamond", 0) for p in players) / len(players)
        avg_elo = sum(p.get("elo", 1000) for p in players) / len(players)
        
        return {
            "table": "players",
            "total_players": len(players),
            "players_with_username": with_username,
            "players_without_username": without_username,
            "average_gold": round(avg_gold, 2),
            "average_diamond": round(avg_diamond, 2),
            "average_elo": round(avg_elo, 2),
            "latest_player": players[-1] if players else None
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "internalError", "message": str(e)})

@app.delete("/dev/players/clear", tags=["Development"])
async def clear_all_players():
    """Development endpoint - DANGER: Clear all players (for testing only)"""
    try:
        # Get count before deletion
        count_result = supabase.table("players").select("device_id").execute()
        initial_count = len(count_result.data) if count_result.data else 0
        
        # Delete all players
        result = supabase.table("players").delete().neq("device_id", "").execute()
        
        return {
            "success": True,
            "message": f"Cleared all players from database",
            "deleted_count": initial_count
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "internalError", "message": str(e)})

# WebSocket endpoint for lobby real-time communication
@app.websocket("/ws/lobby/{lobby_code}")
async def websocket_lobby_endpoint(websocket: WebSocket, lobby_code: str, device_id: str):
    """
    WebSocket endpoint for real-time lobby communication
    
    Parameters:
    - lobby_code: 4-character lobby code
    - device_id: Player's device ID (passed as query parameter)
    
    Usage: ws://localhost:8000/ws/lobby/ABCD?device_id=your_device_id
    """
    handler = get_websocket_handler()
    await handler.handle_connection(websocket, lobby_code, device_id)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000) 