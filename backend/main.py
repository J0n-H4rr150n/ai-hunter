"""
FastAPI Backend for AI Hunter
Provides REST API and WebSocket endpoints for mission control
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
import asyncio
import json
import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from urllib.parse import urlparse, urlunparse

# Import existing components
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from core.autonomous_loop import AutonomousLoop
from core.quota_manager import QuotaManager
from core.agent_tracker import AgentTracker
from memory.finding_repository import FindingRepository
from backend.database import Database
from backend.redis_manager import RedisManager

# Setup logging
log_dir = Path(__file__).parent.parent / "hive_bucket" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

# Backend logger
backend_logger = logging.getLogger("backend")
backend_logger.setLevel(logging.DEBUG)

# File handler with rotation (10MB max, keep 5 backups)
backend_handler = RotatingFileHandler(
    log_dir / "backend.log",
    maxBytes=10*1024*1024,
    backupCount=5
)
backend_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))
backend_logger.addHandler(backend_handler)

# Also log to console
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
backend_logger.addHandler(console_handler)

backend_logger.info("="*60)
backend_logger.info("Backend logger initialized")
backend_logger.info("="*60)

app = FastAPI(title="AI Hunter API", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
db = Database()
redis_mgr = RedisManager()
active_missions = {}
plan_approval_queues = {}  # mission_id -> asyncio.Queue for plan approvals

# Helper function to publish mission updates
async def publish_mission_update(mission_id: int, message: str, event_type: str = "mission_log"):
    """Publish a mission update to the UI"""
    await redis_mgr.publish_event("missions:all", {
        "type": event_type,
        "mission_id": mission_id,
        "message": message,
        "timestamp": datetime.utcnow().isoformat()
    })

# Utility function for Docker networking
def transform_url_for_docker(url: str) -> str:
    """Transform localhost URLs to work from inside Docker container"""
    # Check if running in Docker (common environment variable)
    if not os.path.exists('/.dockerenv'):
        return url  # Not in Docker, return as-is
    
    parsed = urlparse(url)
    if parsed.hostname in ['localhost', '127.0.0.1']:
        # Replace with Docker's host gateway
        netloc = f"host.docker.internal:{parsed.port}" if parsed.port else "host.docker.internal"
        transformed = urlunparse((
            parsed.scheme,
            netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment
        ))
        print(f"[Docker] Transformed {url} → {transformed}")
        return transformed
    
    return url

# Pydantic models
class MissionStart(BaseModel):
    target_url: str
    instructions: Optional[str] = None

class PlanApproval(BaseModel):
    plan: dict

# SSE event stream generator
async def event_stream(mission_id: Optional[int] = None):
    """Server-Sent Events stream for real-time updates"""
    # Subscribe to Redis channel
    channel = f"mission:{mission_id}" if mission_id else "missions:all"
    backend_logger.info(f"SSE client subscribing to {channel}")
    print(f"🔊 SSE client subscribing to {channel}")
    
    # Create dedicated pubsub for this connection
    pubsub = await redis_mgr.subscribe(channel)
    
    try:
        async for event in redis_mgr.listen(pubsub):
            # Format as SSE
            event_type = event.get('type', 'message')
            backend_logger.debug(f"SSE sending event type='{event_type}' to client")
            print(f"📡 SSE sending event type='{event_type}' to client")
            
            # SSE format: event: type\ndata: json\n\n
            sse_message = f"event: {event_type}\ndata: {json.dumps(event)}\n\n"
            backend_logger.debug(f"SSE message: {sse_message[:200]}...")
            print(f"📤 SSE message: {sse_message[:200]}...")
            yield sse_message
    except asyncio.CancelledError:
        backend_logger.info(f"SSE stream cancelled for {channel}")
        print(f"❌ SSE stream cancelled for {channel}")
    finally:
        await pubsub.close()

# Routes
@app.get("/")
async def root():
    return {"status": "online", "service": "AI Hunter API"}

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "database": await db.check_connection(),
        "timestamp": datetime.utcnow().isoformat()
    }

# Frontend logging endpoint
class FrontendLog(BaseModel):
    level: str
    message: str
    timestamp: Optional[str] = None
    data: Optional[dict] = None

@app.post("/api/log/frontend")
async def log_frontend(log_entry: FrontendLog):
    """Receive logs from frontend and write to frontend.log"""
    log_dir = Path(__file__).parent.parent / "hive_bucket" / "logs"
    log_file = log_dir / "frontend.log"
    
    timestamp = log_entry.timestamp or datetime.utcnow().isoformat()
    log_line = f"{timestamp} - {log_entry.level} - {log_entry.message}"
    if log_entry.data:
        log_line += f" - {json.dumps(log_entry.data)}"
    log_line += "\n"
    
    with open(log_file, "a") as f:
        f.write(log_line)
    
    return {"status": "logged"}

@app.get("/api/events")
async def events_all(request: Request):
    """SSE endpoint for all mission events"""
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )

@app.get("/api/events/{mission_id}")
async def events_mission(mission_id: int, request: Request):
    """SSE endpoint for specific mission events"""
    return StreamingResponse(
        event_stream(mission_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@app.post("/api/missions/start")
async def start_mission(mission: MissionStart):
    """Start a new autonomous mission"""
    backend_logger.info(f"Starting mission: {mission.target_url}")
    # Transform URL for Docker if needed
    target_url = transform_url_for_docker(mission.target_url)
    backend_logger.debug(f"Transformed URL: {target_url}")
    
    # Create mission in database
    mission_id = await db.create_mission(
        target_url=target_url,
        instructions=mission.instructions
    )
    
    # Initialize components
    tracker = AgentTracker(agent_id=f"mission_{mission_id}")
    repo = FindingRepository()
    quota = QuotaManager(agent_id=f"mission_{mission_id}")
    
    auto_loop = AutonomousLoop(tracker, repo, quota)
    
    # Create approval queue for this mission
    approval_queue = asyncio.Queue()
    plan_approval_queues[mission_id] = approval_queue
    
    # Store in active missions
    active_missions[mission_id] = {
        "loop": auto_loop,
        "tracker": tracker,
        "repo": repo,
        "quota": quota,
        "status": "planning",
        "approval_queue": approval_queue
    }
    
    # Start mission asynchronously (will pause at approval gate)
    asyncio.create_task(run_mission(mission_id, auto_loop, target_url, mission.instructions, approval_queue))
    
    # Publish mission started event
    await publish_mission_update(mission_id, f"🚀 Mission started: {target_url}", "mission_started")
    
    return {
        "mission_id": mission_id,
        "status": "started",
        "message": "Mission started, generating plan..."
    }

async def run_mission(mission_id: int, auto_loop: AutonomousLoop, target_url: str, instructions: Optional[str], approval_queue: asyncio.Queue):
    """Run the mission loop (async wrapper)"""
    try:
        # Get reference to the current event loop
        main_loop = asyncio.get_event_loop()
        
        # Set up UI callback to publish logs in real-time
        def ui_log_callback(message: str):
            # All messages from log_to_ui get published
            asyncio.run_coroutine_threadsafe(
                publish_mission_update(mission_id, message),
                main_loop
            )
        
        auto_loop.ui_callback = ui_log_callback
        auto_loop.mission_id = mission_id
        
        # Publish initial status
        await publish_mission_update(mission_id, f"🚀 Mission {mission_id} started", "mission_started")
        
        # Custom approval callback that waits for web UI response
        async def async_web_approval(plan: dict) -> tuple[bool, dict]:
            # Publish plan to frontend via Redis
            backend_logger.info(f"[Mission {mission_id}] Publishing plan to Redis...")
            print(f"[Mission {mission_id}] Publishing plan to Redis...")
            backend_logger.debug(f"[Mission {mission_id}] Plan content: {json.dumps(plan, indent=2)[:500]}...")
            print(f"[Mission {mission_id}] Plan content: {json.dumps(plan, indent=2)[:500]}...")
            
            event_data = {
                "type": "plan_generated",
                "mission_id": mission_id,
                "plan": plan
            }
            print(f"[Mission {mission_id}] Event data keys: {list(event_data.keys())}")
            
            await redis_mgr.publish_event("missions:all", event_data)
            print(f"[Mission {mission_id}] Plan published, waiting for web UI approval...")
            
            # Wait for approval response from queue
            approval_response = await approval_queue.get()
            approved = approval_response.get("approved", False)
            edited_plan = approval_response.get("plan", plan)
            
            return (approved, edited_plan)
        
        # Synchronous wrapper that can be called from the sync thread
        def sync_web_approval(plan: dict) -> tuple[bool, dict]:
            # Use run_coroutine_threadsafe to run async code from sync thread
            future = asyncio.run_coroutine_threadsafe(async_web_approval(plan), main_loop)
            return future.result()  # Block until result is available
        
        # Inject the synchronous callback into auto_loop
        auto_loop.web_approval_callback = sync_web_approval
        
        # Run mission in thread pool (since autonomous_loop is synchronous)
        await asyncio.to_thread(
            auto_loop.start_mission,
            f"Audit {target_url} for vulnerabilities",
            target_url,
            instructions
        )
        
        # Mission completed
        await db.update_mission_status(mission_id, "completed")
        await redis_mgr.publish_event("missions:all", {
            "type": "mission_complete",
            "mission_id": mission_id,
            "summary": "Mission completed successfully"
        })
        
    except Exception as e:
        print(f"[Mission {mission_id}] Error: {e}")
        await db.update_mission_status(mission_id, "failed")
        await redis_mgr.publish_event("missions:all", {
            "type": "mission_failed",
            "mission_id": mission_id,
            "error": str(e)
        })
    finally:
        # Clean up
        if mission_id in active_missions:
            del active_missions[mission_id]
        if mission_id in plan_approval_queues:
            del plan_approval_queues[mission_id]

@app.post("/api/missions/{mission_id}/approve")
async def approve_plan(mission_id: int, approval: PlanApproval):
    """Approve a mission plan"""
    if mission_id not in active_missions:
        raise HTTPException(status_code=404, detail="Mission not found")
    
    # Send approval to the waiting mission
    approval_queue = plan_approval_queues.get(mission_id)
    if approval_queue:
        await approval_queue.put({
            "approved": True,
            "plan": approval.plan
        })
    
    # Update database
    await db.update_mission_plan(mission_id, approval.plan, approved=True)
    await db.update_mission_status(mission_id, "executing")
    
    # Notify via SSE
    await redis_mgr.publish_event("missions:all", {
        "type": "plan_approved",
        "mission_id": mission_id
    })
    
    return {"status": "approved"}

@app.post("/api/missions/{mission_id}/reject")
async def reject_plan(mission_id: int):
    """Reject a mission plan"""
    if mission_id not in active_missions:
        raise HTTPException(status_code=404, detail="Mission not found")
    
    # Send rejection to the waiting mission
    approval_queue = plan_approval_queues.get(mission_id)
    if approval_queue:
        await approval_queue.put({
            "approved": False,
            "plan": None
        })
    
    # Update database
    await db.update_mission_status(mission_id, "rejected")
    
    # Notify via SSE
    await redis_mgr.publish_event("missions:all", {
        "type": "plan_rejected",
        "mission_id": mission_id
    })
    
    # Clean up
    if mission_id in active_missions:
        del active_missions[mission_id]
    if mission_id in plan_approval_queues:
        del plan_approval_queues[mission_id]
    
    return {"status": "rejected"}

@app.get("/api/missions/{mission_id}")
async def get_mission(mission_id: int):
    """Get mission details"""
    mission = await db.get_mission(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    return mission

@app.get("/api/missions")
async def list_missions():
    """List all missions"""
    missions = await db.list_missions()
    return missions

# WebSocket endpoint removed - using SSE instead

@app.on_event("startup")
async def startup():
    """Initialize database and connections"""
    backend_logger.info("Starting backend API...")
    await db.initialize()
    await redis_mgr.connect()
    backend_logger.info("🚀 Backend API started")
    print("🚀 Backend API started")

@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown"""
    await db.close()
    await redis_mgr.disconnect()
    print("👋 Backend API stopped")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
