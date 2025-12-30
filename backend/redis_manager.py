"""
Redis pub/sub integration for real-time updates
"""

import redis.asyncio as redis
import json
from typing import Optional
import os

class RedisManager:
    """Manages Redis pub/sub for real-time events"""
    
    def __init__(self):
        self.redis_url = os.getenv("REDIS_URL", "redis://redis:6379")
        self.client: Optional[redis.Redis] = None
    
    async def connect(self):
        """Initialize Redis connection"""
        if not self.client:
            self.client = await redis.from_url(self.redis_url, decode_responses=True)
            print("✅ Redis connected")
    
    async def disconnect(self):
        """Close Redis connection"""
        if self.client:
            await self.client.close()
            print("👋 Redis disconnected")
    
    async def publish_event(self, channel: str, event_data: dict):
        """Publish an event to a channel"""
        if not self.client:
            await self.connect()
        
        message = json.dumps(event_data)
        result = await self.client.publish(channel, message)
        print(f"✅ Redis published to {channel}: {result} subscribers received")
    
    async def publish_mission_event(self, mission_id: int, event_type: str, data: dict):
        """Publish a mission-specific event"""
        event = {
            "type": event_type,
            "mission_id": mission_id,
            "timestamp": data.get("timestamp"),
            "data": data
        }
        await self.publish_event(f"mission:{mission_id}", event)
        # Also publish to general channel
        await self.publish_event("missions:all", event)
    
    async def subscribe(self, *channels):
        """Subscribe to channels - returns a new pubsub instance for this subscriber"""
        if not self.client:
            await self.connect()
        
        # Create a NEW pubsub instance for each subscriber
        pubsub = self.client.pubsub()
        await pubsub.subscribe(*channels)
        return pubsub
    
    async def listen(self, pubsub):
        """Listen for messages (async generator)"""
        async for message in pubsub.listen():
            if message['type'] == 'message':
                try:
                    yield json.loads(message['data'])
                except json.JSONDecodeError:
                    yield message['data']
