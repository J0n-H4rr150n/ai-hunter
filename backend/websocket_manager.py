"""
WebSocket manager for real-time updates to frontend clients
"""

from fastapi import WebSocket
from typing import List
import json

class WebSocketManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        """Accept and store new WebSocket connection"""
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"✅ WebSocket connected (total: {len(self.active_connections)})")
    
    def disconnect(self, websocket: WebSocket):
        """Remove WebSocket connection"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            print(f"❌ WebSocket disconnected (total: {len(self.active_connections)})")
    
    async def send_to(self, websocket: WebSocket, message: dict):
        """Send message to specific websocket"""
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            print(f"Failed to send to websocket: {e}")
            self.disconnect(websocket)
    
    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients"""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except Exception as e:
                print(f"Failed to broadcast to connection: {e}")
                disconnected.append(connection)
        
        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)
