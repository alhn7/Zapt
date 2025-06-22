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

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint - basic welcome message"""
    return {
        "message": "FastAPI Host Checker is running!",
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

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000) 