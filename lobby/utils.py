import random
import string
import logging
import json
from datetime import datetime
from typing import Optional
from pathlib import Path

# Configure logging for lobby events
def setup_lobby_logger():
    """Setup logger for lobby events that writes to lobby_events.log"""
    logger = logging.getLogger('lobby_events')
    logger.setLevel(logging.INFO)
    
    # Remove existing handlers to avoid duplicates
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Create file handler
    log_file = Path("lobby_events.log")
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.propagate = False  # Prevent propagation to root logger
    
    return logger

# Initialize logger
lobby_logger = setup_lobby_logger()

def generate_lobby_code() -> str:
    """
    Generate a random 4-character alphanumeric lobby code.
    Uses uppercase letters and digits for better readability.
    Excludes potentially confusing characters like 0, O, 1, I.
    """
    # Use clear characters only (no 0, O, 1, I)
    clear_chars = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'
    return ''.join(random.choice(clear_chars) for _ in range(4))

def is_valid_lobby_code(code: str) -> bool:
    """Validate if a lobby code format is correct"""
    return (
        isinstance(code, str) and 
        len(code) == 4 and 
        code.isalnum() and 
        code.isupper()
    )

def log_lobby_event(event_type: str, data: dict, device_id: Optional[str] = None):
    """
    Log lobby events to the lobby_events.log file
    
    Args:
        event_type: Type of event (create, join, leave, ready_toggle, etc.)
        data: Event data dictionary
        device_id: Optional device ID of the player who triggered the event
    """
    try:
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "device_id": device_id,
            "data": data
        }
        
        lobby_logger.info(json.dumps(log_entry, default=str))
        
    except Exception as e:
        # Fallback logging if JSON serialization fails
        lobby_logger.error(f"Failed to log event {event_type}: {str(e)}")

def validate_device_id(device_id: str) -> bool:
    """Basic validation for device ID"""
    return isinstance(device_id, str) and len(device_id.strip()) > 0

def calculate_estimated_wait_time(queue_position: int) -> int:
    """
    Calculate estimated wait time based on queue position
    This is a simple estimation - you can make it more sophisticated
    
    Args:
        queue_position: Position in the matchmaking queue (1-based)
    
    Returns:
        Estimated wait time in seconds
    """
    if queue_position <= 1:
        return 0
    
    # Assume 30 seconds average per match formation
    # If position is 3, that means 1 person ahead, so ~15 seconds wait
    people_ahead = queue_position - 1
    matches_ahead = (people_ahead + 1) // 2  # Every 2 people form a match
    
    # Estimate 15-30 seconds per match formation
    base_time = matches_ahead * 20
    
    # Add some variance (±10 seconds)
    variance = random.randint(-10, 10)
    
    return max(5, base_time + variance)  # Minimum 5 seconds

def get_lobby_summary(lobby_data: dict, members_data: list) -> str:
    """Generate a human-readable summary of lobby state for logging"""
    return (
        f"Lobby {lobby_data.get('code')} "
        f"({lobby_data.get('status')}) - "
        f"{len(members_data)}/{lobby_data.get('max_players')} players"
    )

def is_countdown_active(countdown_start_time: Optional[datetime]) -> bool:
    """Check if countdown is currently active (within 3 seconds)"""
    if not countdown_start_time:
        return False
    
    elapsed = (datetime.now() - countdown_start_time.replace(tzinfo=None)).total_seconds()
    return 0 <= elapsed < 3

def get_countdown_remaining(countdown_start_time: datetime) -> int:
    """Get remaining countdown time in seconds (0-3)"""
    elapsed = (datetime.now() - countdown_start_time.replace(tzinfo=None)).total_seconds()
    remaining = max(0, 3 - int(elapsed))
    return remaining 