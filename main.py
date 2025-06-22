from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn
from datetime import datetime
import platform
import socket

# Create FastAPI instance
app = FastAPI(
    title="Host Status Checker API",
    description="A simple FastAPI application to check if the host is working",
    version="1.0.0"
)

# Response models
class HealthResponse(BaseModel):
    status: str
    message: str
    timestamp: str
    host_info: dict

class StatusResponse(BaseModel):
    status: str
    uptime: str
    host: str
    platform: str

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint - basic welcome message"""
    return {
        "message": "FastAPI Host Checker is running!",
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    }

# Health check endpoint
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Comprehensive health check endpoint"""
    hostname = socket.gethostname()
    host_ip = socket.gethostbyname(hostname)
    
    return HealthResponse(
        status="healthy",
        message="Host is working properly",
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

# Simple status endpoint
@app.get("/status", response_model=StatusResponse)
async def status():
    """Simple status check endpoint"""
    return StatusResponse(
        status="running",
        uptime=datetime.now().isoformat(),
        host=socket.gethostname(),
        platform=platform.system()
    )

# Ping endpoint
@app.get("/ping")
async def ping():
    """Simple ping endpoint for quick connectivity check"""
    return {"ping": "pong", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000) 