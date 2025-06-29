#!/usr/bin/env python3

import requests
import json

# Test configuration
SERVER_URL = "http://0.0.0.0:8000/"
DEVICE_ID = "aa"

def make_request(method, endpoint, data=None):
    """Make HTTP request with device ID header"""
    headers = {
        "Content-Type": "application/json",
        "X-Device-ID": DEVICE_ID
    }
    
    url = f"{SERVER_URL}{endpoint}"
    
    try:
        if method == "GET":
            response = requests.get(url, headers=headers)
        elif method == "POST":
            response = requests.post(url, headers=headers, json=data or {})
        
        # Handle JSON response safely
        try:
            json_data = response.json()
        except:
            json_data = {"error": "Invalid JSON response", "text": response.text}
        
        return response.status_code, json_data
    except Exception as e:
        return 500, {"error": f"Request failed: {str(e)}"}

def test_edge_cases():
    print("🧪 Testing Edge Cases for Lobby System")
    print("=" * 50)
    
    # First: Create the test user
    print("\n0. Creating test user...")
    create_user_data = {"device_id": DEVICE_ID}
    try:
        response = requests.post(f"{SERVER_URL}/players", json=create_user_data, headers={"Content-Type": "application/json"})
        if response.status_code == 200:
            print(f"✅ Test user created: {DEVICE_ID}")
        elif response.status_code == 400:
            print(f"ℹ️ Test user already exists: {DEVICE_ID}")
        else:
            print(f"⚠️ User creation response: {response.status_code}")
    except Exception as e:
        print(f"⚠️ User creation failed: {e}")
    
    # Test 1: Create a lobby
    print("\n1. Creating a lobby...")
    status, data = make_request("POST", "/lobby/create")
    
    if status == 200 and data.get("success"):
        lobby_code = data["lobby"]["code"]
        print(f"✅ Lobby created: {lobby_code}")
    else:
        print(f"❌ Failed to create lobby: {data}")
        return
    
    # Test 2: Try to join own lobby
    print(f"\n2. Trying to join own lobby ({lobby_code})...")
    status, data = make_request("POST", "/lobby/join", {"code": lobby_code})
    
    if status == 200 and not data.get("success"):
        print(f"✅ Correctly blocked: {data['message']}")
    else:
        print(f"❌ Should have been blocked: {data}")
    
    # Test 3: Try matchmaking while in lobby
    print("\n3. Trying matchmaking while in lobby...")
    status, data = make_request("POST", "/lobby/find_match")
    
    if status == 200 and not data.get("success"):
        print(f"✅ Correctly blocked: {data['message']}")
    else:
        print(f"❌ Should have been blocked: {data}")
    
    # Test 4: Try to join non-existent lobby
    print("\n4. Trying to join non-existent lobby...")
    status, data = make_request("POST", "/lobby/join", {"code": "XXXX"})
    
    if status == 200 and not data.get("success"):
        print(f"✅ Correctly blocked: {data['message']}")
    else:
        print(f"❌ Should have been blocked: {data}")
    
    # Test 5: Try invalid lobby code format
    print("\n5. Trying invalid lobby code format...")
    status, data = make_request("POST", "/lobby/join", {"code": "ABC"})
    
    if status == 200 and not data.get("success"):
        print(f"✅ Correctly blocked: {data['message']}")
    else:
        print(f"❌ Should have been blocked: {data}")
    
    print("\n" + "=" * 50)
    print("🎉 Edge case testing completed!")

if __name__ == "__main__":
    test_edge_cases() 