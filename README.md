# FastAPI Host Status Checker

A simple FastAPI application to check if the host is working properly. This project provides multiple endpoints to verify server health and connectivity.

## Features

- **Health Check**: Comprehensive endpoint that returns host information
- **Status Check**: Simple status endpoint with basic system info
- **Ping Endpoint**: Quick connectivity test
- **Root Endpoint**: Basic welcome message

## Installation

1. Install the required dependencies:
```bash
pip install -r requirements.txt
```

## Running the Application

### Method 1: Using Python directly
```bash
python main.py
```

### Method 2: Using Uvicorn command
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The application will be available at `http://localhost:8000`

## API Endpoints

- `GET /` - Root endpoint with welcome message
- `GET /health` - Comprehensive health check with host information
- `GET /status` - Simple status check
- `GET /ping` - Quick ping test

## Testing the Endpoints

Once the server is running, you can test the endpoints:

```bash
# Basic connectivity test
curl http://localhost:8000/

# Health check
curl http://localhost:8000/health

# Status check
curl http://localhost:8000/status

# Ping test
curl http://localhost:8000/ping
```

## API Documentation

FastAPI automatically generates interactive API documentation:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

## Example Response

Health check endpoint response:
```json
{
  "status": "healthy",
  "message": "Host is working properly",
  "timestamp": "2024-01-01T12:00:00.000000",
  "host_info": {
    "hostname": "your-hostname",
    "ip_address": "192.168.1.100",
    "platform": "Darwin",
    "platform_release": "23.1.0",
    "architecture": "arm64",
    "processor": "arm"
  }
}
``` 