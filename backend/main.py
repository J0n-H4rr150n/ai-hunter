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
from core.state_manager import StateManager
from tools.som_browser import SoMBrowser  # Add browser import
from core.playbook_manager import PlaybookManager
from core.playbook_executor import PlaybookExecutor

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
state_mgr = None  # Initialize after db is ready
active_missions = {}
plan_approval_queues = {}  # mission_id -> asyncio.Queue for plan approvals
tool_approval_queues = {}  # mission_id -> asyncio.Queue for tool approvals (HITL)

# Helper function to publish mission updates
async def publish_mission_update(mission_id: int, message: str, event_type: str = "mission_log", screenshot: dict = None):
    """Publish a mission update to the UI"""
    event_data = {
        "type": event_type,
        "mission_id": mission_id,
        "message": message,
        "timestamp": datetime.utcnow().isoformat()
    }
    if screenshot:
        event_data["screenshot"] = screenshot
    
    await redis_mgr.publish_event("missions:all", event_data)

# API endpoint to serve screenshots
@app.get("/api/screenshots/{date}/{mission_id}/{filename}")
async def get_screenshot(date: str, mission_id: str, filename: str):
    """Serve screenshot images from hive_bucket"""
    from fastapi.responses import FileResponse
    import os
    
    # Construct path to screenshot
    screenshot_path = Path(__file__).parent.parent / "hive_bucket" / "screenshots" / date / mission_id / filename
    
    backend_logger.debug(f"Screenshot request: {screenshot_path}")
    
    if not screenshot_path.exists():
        backend_logger.warning(f"Screenshot not found: {screenshot_path}")
        raise HTTPException(status_code=404, detail="Screenshot not found")
    
    return FileResponse(screenshot_path, media_type="image/png")

@app.get("/api/missions/{mission_id}/artifacts")
async def get_mission_artifacts(mission_id: int):
    """Get all artifacts (screenshots, metadata) for a mission"""
    from datetime import date
    import glob
    
    artifacts = {
        "screenshots": [],
        "metadata": [],
        "findings": []
    }
    
    # Find mission directory
    today = date.today().strftime("%Y-%m-%d")
    mission_dir = Path(__file__).parent.parent / "hive_bucket" / "screenshots" / today / f"mission_{mission_id}"
    
    if mission_dir.exists():
        # List all screenshots
        for png_file in mission_dir.glob("*.png"):
            json_file = png_file.with_suffix('.json')
            artifact = {
                "type": "screenshot",
                "filename": png_file.name,
                "timestamp": png_file.stem.split('_')[0],
                "action": '_'.join(png_file.stem.split('_')[1:]),
                "url": f"/api/screenshots/{today}/mission_{mission_id}/{png_file.name}",
                "has_metadata": json_file.exists(),
                "metadata_url": f"/api/missions/{mission_id}/metadata/{json_file.name}" if json_file.exists() else None
            }
            artifacts["screenshots"].append(artifact)
        
        # List all metadata files
        for json_file in mission_dir.glob("*.json"):
            artifacts["metadata"].append({
                "filename": json_file.name,
                "url": f"/api/missions/{mission_id}/metadata/{json_file.name}"
            })
    
    # Get findings from repository
    findings_dir = Path(__file__).parent.parent / "hive_bucket" / "findings"
    if findings_dir.exists():
        for type_dir in findings_dir.iterdir():
            if type_dir.is_dir():
                for finding_file in type_dir.glob("*.json"):
                    artifacts["findings"].append({
                        "type": type_dir.name,
                        "filename": finding_file.name,
                        "url": f"/api/findings/{type_dir.name}/{finding_file.name}"
                    })
    
    return artifacts

@app.get("/api/missions/{mission_id}/metadata/{filename}")
async def get_mission_metadata(mission_id: int, filename: str):
    """Serve metadata JSON files"""
    from fastapi.responses import JSONResponse
    from datetime import date
    
    today = date.today().strftime("%Y-%m-%d")
    metadata_path = Path(__file__).parent.parent / "hive_bucket" / "screenshots" / today / f"mission_{mission_id}" / filename
    
    if not metadata_path.exists():
        raise HTTPException(status_code=404, detail="Metadata not found")
    
    with open(metadata_path, 'r') as f:
        data = json.load(f)
    
    return JSONResponse(content=data)

@app.get("/api/findings/{finding_type}/{filename}")
async def get_finding(finding_type: str, filename: str):
    """Serve finding JSON files"""
    from fastapi.responses import JSONResponse
    
    finding_path = Path(__file__).parent.parent / "hive_bucket" / "findings" / finding_type / filename
    
    if not finding_path.exists():
        raise HTTPException(status_code=404, detail="Finding not found")
    
    with open(finding_path, 'r') as f:
        data = json.load(f)
    
    return JSONResponse(content=data)

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

class PlaybookMissionStart(BaseModel):
    target_url: str
    playbook_name: str
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
# NOTE: "/" is deliberately not claimed here. In single-port mode (serve.py) the SPA
# is mounted at the root, so the API advertises itself under /api/status instead.
@app.get("/api/status")
async def api_status():
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
    
    auto_loop = AutonomousLoop(tracker, repo, quota, db)
    
    # Create approval queue for this mission
    approval_queue = asyncio.Queue()
    plan_approval_queues[mission_id] = approval_queue
    
    # Create tool approval queue for HITL
    tool_approval_queue = asyncio.Queue()
    tool_approval_queues[mission_id] = tool_approval_queue
    
    # Store in active missions
    active_missions[mission_id] = {
        "loop": auto_loop,
        "tracker": tracker,
        "repo": repo,
        "quota": quota,
        "status": "planning",
        "approval_queue": approval_queue,
        "tool_approval_queue": tool_approval_queue
    }
    
    # Start mission asynchronously (will pause at approval gate)
    asyncio.create_task(run_mission(mission_id, auto_loop, target_url, mission.instructions, approval_queue, tool_approval_queue))
    
    # Publish mission started event
    await publish_mission_update(mission_id, f"🚀 Mission started: {target_url}", "mission_started")
    
    return {
        "mission_id": mission_id,
        "status": "started",
        "message": "Mission started, generating plan..."
    }

async def run_mission(mission_id: int, auto_loop: AutonomousLoop, target_url: str, instructions: Optional[str], approval_queue: asyncio.Queue, tool_approval_queue: asyncio.Queue):
    """Run the mission loop (async wrapper)"""
    try:
        # Get reference to the current event loop
        main_loop = asyncio.get_event_loop()
        
        # Load settings for this mission
        settings = await db.get_settings(mission_id)
        hitl_enabled = settings.get('hitl_enabled', {}).get('enabled', False) if isinstance(settings.get('hitl_enabled'), dict) else settings.get('hitl_enabled', False)
        auto_approve_tools = settings.get('auto_approve_tools', ['view_raw_source', 'view_dom', 'check_network'])
        
        backend_logger.info(f"[Mission {mission_id}] HITL enabled: {hitl_enabled}, Auto-approve: {auto_approve_tools}")
        
        # Set up UI callback to publish logs in real-time
        def ui_log_callback(message: str, screenshot: dict = None):
            # All messages from log_to_ui get published
            asyncio.run_coroutine_threadsafe(
                publish_mission_update(mission_id, message, "mission_log", screenshot),
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
        
        # Tool approval callback for HITL
        async def async_tool_approval(tool_name: str, tool_inputs: dict, context: dict) -> dict:
            """Request approval for a tool call"""
            # Check if HITL is enabled
            if not hitl_enabled:
                backend_logger.debug(f"[Mission {mission_id}] HITL disabled, auto-approving: {tool_name}")
                return {'approved': True, 'edited_inputs': tool_inputs, 'feedback': None}
            
            # Check if tool is auto-approved
            if tool_name in auto_approve_tools:
                backend_logger.debug(f"[Mission {mission_id}] Auto-approving tool: {tool_name}")
                return {'approved': True, 'edited_inputs': tool_inputs, 'feedback': None}
            
            # Request human approval
            backend_logger.info(f"[Mission {mission_id}] Requesting approval for: {tool_name}")
            print(f"[HITL Backend] Publishing approval request for {tool_name}")
            
            event_data = {
                "type": "tool_approval_request",
                "mission_id": mission_id,
                "tool_name": tool_name,
                "tool_inputs": tool_inputs,
                "context": context,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            await redis_mgr.publish_event("missions:all", event_data)
            print(f"[HITL Backend] Published, now waiting for response...")
            
            # Wait for approval response
            start_time = datetime.utcnow()
            approval_response = await tool_approval_queue.get()
            response_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            print(f"[HITL Backend] Received response after {response_time_ms}ms: approved={approval_response.get('approved')}")
            
            # Save to database
            await db.save_tool_approval(
                mission_id=mission_id,
                tool_name=tool_name,
                tool_inputs=tool_inputs,
                approved=approval_response.get('approved', False),
                context=context,
                feedback=approval_response.get('feedback'),
                edited_inputs=approval_response.get('edited_inputs'),
                response_time_ms=response_time_ms
            )
            
            return approval_response
        
        def sync_tool_approval(tool_name: str, tool_inputs: dict, context: dict) -> dict:
            """Synchronous wrapper for tool approval"""
            future = asyncio.run_coroutine_threadsafe(async_tool_approval(tool_name, tool_inputs, context), main_loop)
            return future.result()
        
        # Inject tool approval callback
        auto_loop.tool_approval_callback = sync_tool_approval
        auto_loop.hitl_enabled = hitl_enabled
        
        # Run mission (now properly async)
        await auto_loop.start_mission(
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

@app.get("/api/playbooks")
async def list_playbooks():
    """List all available playbooks"""
    try:
        playbook_mgr = PlaybookManager()
        playbooks = playbook_mgr.get_available_playbooks()
        return playbooks
    except Exception as e:
        backend_logger.error(f"Failed to list playbooks: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/playbooks/{playbook_name}")
async def get_playbook(playbook_name: str):
    """Get details of a specific playbook"""
    try:
        playbook_mgr = PlaybookManager()
        playbook = playbook_mgr.load_playbook(playbook_name)
        
        if not playbook:
            raise HTTPException(status_code=404, detail="Playbook not found")
        
        return playbook
    except HTTPException:
        raise
    except Exception as e:
        backend_logger.error(f"Failed to get playbook {playbook_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/missions/start-playbook")
async def start_playbook_mission(mission: PlaybookMissionStart):
    """Start a new playbook-based mission"""
    backend_logger.info(f"Starting playbook mission: {mission.playbook_name} on {mission.target_url}")
    
    # Transform URL for Docker if needed
    target_url = transform_url_for_docker(mission.target_url)
    backend_logger.debug(f"Transformed URL: {target_url}")
    
    # Validate playbook exists
    playbook_mgr = PlaybookManager()
    playbook = playbook_mgr.load_playbook(mission.playbook_name)
    if not playbook:
        raise HTTPException(status_code=404, detail=f"Playbook '{mission.playbook_name}' not found")
    
    # Create mission in database
    mission_id = await db.create_mission(
        target_url=target_url,
        instructions=f"Playbook: {mission.playbook_name}\n{mission.instructions or ''}"
    )
    
    # Initialize components
    tracker = AgentTracker(agent_id=f"mission_{mission_id}")
    repo = FindingRepository()
    quota = QuotaManager(agent_id=f"mission_{mission_id}")
    state_mgr = StateManager(db)  # Fix: pass db
    
    # Create tool approval queue for HITL
    tool_approval_queue = asyncio.Queue()
    tool_approval_queues[mission_id] = tool_approval_queue
    
    # Publish mission started event
    await redis_mgr.publish_event("missions:all", {
        "type": "mission_started",
        "mission_id": mission_id,
        "message": f"Starting playbook: {mission.playbook_name}",
        "timestamp": datetime.utcnow().isoformat()
    })
    
    # Publish playbook started event
    await redis_mgr.publish_event("missions:all", {
        "type": "playbook_started",
        "mission_id": mission_id,
        "playbook_name": mission.playbook_name,
        "goal": playbook.get("metadata", {}).get("description", ""),
        "total_stages": len(playbook.get("sequence", [])),
        "timestamp": datetime.utcnow().isoformat()
    })
    
    # Store in active missions
    active_missions[mission_id] = {
        "status": "running",
        "playbook": mission.playbook_name,
        "started_at": datetime.utcnow().isoformat()
    }
    
    # Execute playbook in background
    asyncio.create_task(execute_playbook_mission(
        mission_id, mission.playbook_name, target_url, 
        mission.instructions, tracker, repo, quota, state_mgr, tool_approval_queue
    ))
    
    return {
        "mission_id": mission_id,
        "status": "started",
        "playbook": mission.playbook_name
    }

async def execute_playbook_mission(
    mission_id: int,
    playbook_name: str,
    target_url: str,
    instructions: Optional[str],
    tracker: AgentTracker,
    repo: FindingRepository,
    quota: QuotaManager,
    state_mgr: StateManager,
    tool_approval_queue: asyncio.Queue
):
    """Execute a playbook-based mission with step-level LLM planning"""
    try:
        backend_logger.info(f"[Mission {mission_id}] Executing playbook: {playbook_name}")
        
        # Load playbook to get goal/metadata
        playbook_mgr = PlaybookManager()
        playbook = playbook_mgr.load_playbook(playbook_name)
        goal = playbook.get("metadata", {}).get("description", f"Execute {playbook_name}")
        
        # Create AutonomousLoop for browser/tool access
        auto_loop = AutonomousLoop(tracker, repo, quota, db)
        auto_loop.mission_id = mission_id
        
        # Initialize browser in thread pool (Playwright sync API can't run in asyncio loop)
        backend_logger.info("[Playbook] Initializing browser...")
        loop = asyncio.get_event_loop()
        auto_loop.browser = await loop.run_in_executor(None, lambda: SoMBrowser(headless=True))
        auto_loop.tracker.set_browser(auto_loop.browser)
        
        # Get event loop for callbacks
        main_loop = asyncio.get_event_loop()
        
        # Set up UI callback
        def ui_log_callback(message: str, screenshot: dict = None):
            asyncio.run_coroutine_threadsafe(
                publish_mission_update(mission_id, message, "mission_log", screenshot),
                main_loop
            )
        
        auto_loop.ui_callback = ui_log_callback
        
        # Load settings for HITL
        settings = await db.get_settings(mission_id)
        hitl_enabled = settings.get('hitl_enabled', {}).get('enabled', False) if isinstance(settings.get('hitl_enabled'), dict) else settings.get('hitl_enabled', False)
        auto_approve_tools = settings.get('auto_approve_tools', ['view_raw_source', 'view_dom', 'check_network'])
        
        # Tool approval callback
        async def async_tool_approval(tool_name: str, tool_inputs: dict, context: dict) -> dict:
            if not hitl_enabled or tool_name in auto_approve_tools:
                return {'approved': True, 'edited_inputs': tool_inputs, 'feedback': None}
            
            await redis_mgr.publish_event("missions:all", {
                "type": "tool_approval_request",
                "approval_id": f"tool_{mission_id}_{datetime.utcnow().timestamp()}",
                "mission_id": mission_id,
                "tool_name": tool_name,
                "tool_inputs": tool_inputs,
                "context": context,
                "timestamp": datetime.utcnow().isoformat()
            })
            
            approval_response = await tool_approval_queue.get()
            return approval_response
        
        def sync_tool_approval(tool_name: str, tool_inputs: dict, context: dict) -> dict:
            future = asyncio.run_coroutine_threadsafe(
                async_tool_approval(tool_name, tool_inputs, context), 
                main_loop
            )
            return future.result()
        
        auto_loop.tool_approval_callback = sync_tool_approval
        auto_loop.hitl_enabled = hitl_enabled
        
        # Create PlaybookExecutor with initialized AutonomousLoop
        executor = PlaybookExecutor(
            autonomous_loop=auto_loop,  # Now has browser!
            db=db
        )
        
        # Store executor in active missions for checkpoint access
        if mission_id in active_missions:
            active_missions[mission_id]['executor'] = executor
        
        # Progress callback for UI updates
        async def progress_callback(progress_data: dict):
            """Publish playbook progress updates"""
            await redis_mgr.publish_event("missions:all", {
                "type": "playbook_progress",
                "mission_id": mission_id,
                "playbook_name": playbook_name,
                **progress_data,
                "timestamp": datetime.utcnow().isoformat()
            })
        
        # Tool approval callback
        main_loop = asyncio.get_event_loop()
        
        async def async_tool_approval(tool_name: str, tool_inputs: dict, context: dict) -> dict:
            """Request tool approval from user"""
            approval_id = f"tool_{mission_id}_{datetime.utcnow().timestamp()}"
            
            # Publish approval request
            await redis_mgr.publish_event("missions:all", {
                "type": "tool_approval_request",
                "approval_id": approval_id,
                "mission_id": mission_id,
                "tool_name": tool_name,
                "tool_inputs": tool_inputs,
                "context": context,
                "timestamp": datetime.utcnow().isoformat()
            })
            
            # Wait for approval
            approval_response = await tool_approval_queue.get()
            return approval_response
        
        def sync_tool_approval(tool_name: str, tool_inputs: dict, context: dict) -> dict:
            """Synchronous wrapper for tool approval"""
            future = asyncio.run_coroutine_threadsafe(
                async_tool_approval(tool_name, tool_inputs, context), 
                main_loop
            )
            return future.result()
        
        # Configure HITL
        executor.tool_approval_callback = sync_tool_approval
        executor.hitl_enabled = True  # Can be configured per playbook
        
        # Execute playbook (async)
        result = await executor.execute_playbook(
            playbook_name,
            goal=goal,
            target_url=target_url,
            mission_id=mission_id,
            instructions=instructions,
            progress_callback=progress_callback
        )
        
        # Mission completed
        await db.update_mission_status(mission_id, "completed")
        await redis_mgr.publish_event("missions:all", {
            "type": "playbook_completed",
            "mission_id": mission_id,
            "playbook_name": playbook_name,
            "result": result,
            "timestamp": datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        backend_logger.error(f"[Mission {mission_id}] Playbook execution error: {e}", exc_info=True)
        await db.update_mission_status(mission_id, "failed")
        await redis_mgr.publish_event("missions:all", {
            "type": "mission_failed",
            "mission_id": mission_id,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        })
    finally:
        # Clean up
        if mission_id in active_missions:
            del active_missions[mission_id]
        if mission_id in tool_approval_queues:
            del tool_approval_queues[mission_id]

@app.post("/api/missions/{mission_id}/checkpoint")
async def create_mission_checkpoint(mission_id: int):
    """Create a checkpoint for a running playbook mission"""
    if mission_id not in active_missions:
        raise HTTPException(status_code=404, detail="Mission not found")
    
    mission_info = active_missions[mission_id]
    
    # Check if this is a playbook mission with executor
    if 'executor' not in mission_info:
        raise HTTPException(status_code=400, detail="Mission is not a playbook mission")
    
    executor = mission_info['executor']
    
    try:
        checkpoint_name = await executor.create_checkpoint()
        return {
            "checkpoint_name": checkpoint_name,
            "mission_id": mission_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        backend_logger.error(f"Failed to create checkpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/missions/{mission_id}/checkpoints")
async def list_mission_checkpoints(mission_id: int):
    """List all checkpoints for a mission"""
    try:
        state_mgr = StateManager(db)
        checkpoints = await state_mgr.list_checkpoints(mission_id)
        return checkpoints
    except Exception as e:
        backend_logger.error(f"Failed to list checkpoints: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/missions/{mission_id}/restore")
async def restore_mission_checkpoint(mission_id: int, checkpoint_name: str):
    """Restore a mission from a checkpoint"""
    if mission_id not in active_missions:
        raise HTTPException(status_code=404, detail="Mission not found or not running")
    
    mission_info = active_missions[mission_id]
    
    if 'executor' not in mission_info:
        raise HTTPException(status_code=400, detail="Mission is not a playbook mission")
    
    executor = mission_info['executor']
    
    try:
        success = await executor.restore_checkpoint(checkpoint_name)
        if not success:
            raise HTTPException(status_code=404, detail="Checkpoint not found")
        
        return {
            "restored": True,
            "checkpoint_name": checkpoint_name,
            "mission_id": mission_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        backend_logger.error(f"Failed to restore checkpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/missions/{mission_id}/pause-playbook")
async def pause_playbook_mission(mission_id: int):
    """Pause a running playbook mission"""
    if mission_id not in active_missions:
        raise HTTPException(status_code=404, detail="Mission not found")
    
    mission_info = active_missions[mission_id]
    
    if 'executor' not in mission_info:
        raise HTTPException(status_code=400, detail="Mission is not a playbook mission")
    
    executor = mission_info['executor']
    executor.pause_execution()
    
    await redis_mgr.publish_event("missions:all", {
        "type": "playbook_paused",
        "mission_id": mission_id,
        "timestamp": datetime.utcnow().isoformat()
    })
    
    return {"paused": True, "mission_id": mission_id}

@app.post("/api/missions/{mission_id}/resume-playbook")
async def resume_playbook_mission(mission_id: int):
    """Resume a paused playbook mission"""
    if mission_id not in active_missions:
        raise HTTPException(status_code=404, detail="Mission not found")
    
    mission_info = active_missions[mission_id]
    
    if 'executor' not in mission_info:
        raise HTTPException(status_code=400, detail="Mission is not a playbook mission")
    
    executor = mission_info['executor']
    executor.resume_execution()
    
    await redis_mgr.publish_event("missions:all", {
        "type": "playbook_resumed",
        "mission_id": mission_id,
        "timestamp": datetime.utcnow().isoformat()
    })
    
    return {"resumed": True, "mission_id": mission_id}

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

@app.get("/api/settings")
async def get_settings():
    """Get global settings"""
    settings = await db.get_settings()
    # Convert to simple dict
    result = {}
    for key, value in settings.items():
        result[key] = value if not isinstance(value, str) else json.loads(value)
    
    # Flatten nested settings for frontend
    if 'hitl_enabled' in result:
        hitl_config = result['hitl_enabled']
        result['hitl_enabled'] = hitl_config.get('enabled', False)
    
    if 'auto_approve_tools' in result:
        result['auto_approve_tools'] = result['auto_approve_tools']
    else:
        result['auto_approve_tools'] = ['view_raw_source', 'view_dom', 'check_network']
    
    return result

@app.post("/api/settings")
async def update_settings(settings: dict):
    """Update global settings"""
    # Save HITL config
    await db.update_setting('hitl_enabled', {
        'enabled': settings.get('hitl_enabled', False)
    })
    
    # Save auto-approve tools list
    await db.update_setting('auto_approve_tools', settings.get('auto_approve_tools', []))
    
    backend_logger.info(f"Settings updated: {settings}")
    return {"status": "ok"}

@app.post("/api/tools/approve")
async def approve_tool(approval: dict):
    """Approve or reject a tool call"""
    mission_id = approval.get('mission_id')
    approved = approval.get('approved', False)
    feedback = approval.get('feedback', '')
    edited_inputs = approval.get('edited_inputs')
    
    if mission_id in tool_approval_queues:
        await tool_approval_queues[mission_id].put({
            'approved': approved,
            'feedback': feedback,
            'edited_inputs': edited_inputs
        })
        
        # Save to database for training
        await db.save_tool_approval(
            mission_id=mission_id,
            tool_name=approval.get('tool_name', ''),
            tool_inputs=approval.get('tool_inputs', {}),
            approved=approved,
            context=approval.get('context'),
            feedback=feedback,
            edited_inputs=edited_inputs,
            response_time_ms=approval.get('response_time_ms')
        )
        
        return {"status": "ok"}
    return {"error": "Mission not found"}, 404

# Mission control endpoints
@app.post("/api/missions/{mission_id}/pause")
async def pause_mission(mission_id: int):
    """Request mission pause after current task"""
    if mission_id in active_missions:
        active_missions[mission_id]["status"] = "pausing"
        # TODO: Implement actual pause signal to autonomous loop
        await redis_mgr.publish_event("missions:all", {
            "type": "mission_status",
            "mission_id": mission_id,
            "status": "pausing"
        })
        return {"status": "pausing"}
    raise HTTPException(status_code=404, detail="Mission not found")

@app.post("/api/missions/{mission_id}/resume")
async def resume_mission(mission_id: int):
    """Resume paused mission"""
    if mission_id in active_missions:
        active_missions[mission_id]["status"] = "running"
        await redis_mgr.publish_event("missions:all", {
            "type": "mission_status",
            "mission_id": mission_id,
            "status": "running"
        })
        return {"status": "running"}
    raise HTTPException(status_code=404, detail="Mission not found")

@app.post("/api/missions/{mission_id}/stop")
async def stop_mission(mission_id: int):
    """Force stop mission immediately"""
    if mission_id in active_missions:
        # TODO: Implement force stop
        active_missions[mission_id]["status"] = "stopped"
        await db.update_mission_status(mission_id, "stopped")
        await redis_mgr.publish_event("missions:all", {
            "type": "mission_status",
            "mission_id": mission_id,
            "status": "stopped"
        })
        return {"status": "stopped"}
    raise HTTPException(status_code=404, detail="Mission not found")

class UserMessage(BaseModel):
    message: str

@app.post("/api/missions/{mission_id}/message")
async def send_user_message(mission_id: int, msg: UserMessage):
    """Queue user message for agent (will pause after current task)"""
    if mission_id in active_missions:
        # TODO: Implement message queueing
        await redis_mgr.publish_event("missions:all", {
            "type": "user_message",
            "mission_id": mission_id,
            "message": msg.message,
            "timestamp": datetime.utcnow().isoformat()
        })
        return {"status": "queued"}
    raise HTTPException(status_code=404, detail="Mission not found")

# Iteration endpoints
@app.get("/api/missions/{mission_id}/iterations")
async def get_iterations(mission_id: int):
    """Get all iterations for a mission"""
    iterations = await db.get_iterations_for_mission(mission_id)
    return iterations

@app.post("/api/missions/{mission_id}/iterations/{iteration_num}/approve")
async def approve_iteration(mission_id: int, iteration_num: int, approval: PlanApproval):
    """Approve iteration plan and start execution"""
    # Get mission to find iteration
    iterations = await db.get_iterations_for_mission(mission_id)
    iteration = next((i for i in iterations if i['iteration_number'] == iteration_num), None)
    
    if not iteration:
        raise HTTPException(status_code=404, detail="Iteration not found")
    
    # Update iteration status
    await db.update_iteration_status(iteration['id'], "in_progress")
    
    # Notify via SSE
    await redis_mgr.publish_event("missions:all", {
        "type": "iteration_started",
        "mission_id": mission_id,
        "iteration_number": iteration_num,
        "timestamp": datetime.utcnow().isoformat()
    })
    
    return {"status": "approved", "iteration_id": iteration['id']}

@app.post("/api/missions/{mission_id}/replan")
async def replan_mission(mission_id: int):
    """Create next iteration based on previous findings"""
    if mission_id not in active_missions:
        raise HTTPException(status_code=404, detail="Mission not found")
    
    try:
        # Get the autonomous loop instance
        auto_loop = active_missions[mission_id]['loop']
        
        # Get current iteration count
        iterations = await db.get_iterations_for_mission(mission_id)
        current_iteration_num = len(iterations)
        
        # Generate next iteration plan
        next_iteration_id = await auto_loop.generate_next_iteration_plan(mission_id, current_iteration_num)
        
        # Publish event
        await redis_mgr.publish_event("missions:all", {
            "type": "replan_complete",
            "mission_id": mission_id,
            "iteration_id": next_iteration_id,
            "iteration_number": current_iteration_num + 1,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        return {"status": "success", "iteration_id": next_iteration_id, "iteration_number": current_iteration_num + 1}
    except Exception as e:
        backend_logger.error(f"Replan failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# WebSocket endpoint removed - using SSE instead

@app.on_event("startup")
async def startup():
    """Initialize database and connections"""
    global state_mgr
    backend_logger.info("Starting backend API...")
    await db.initialize()
    await redis_mgr.connect()
    state_mgr = StateManager(db)
    backend_logger.info("🚀 Backend API started with state management")
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
