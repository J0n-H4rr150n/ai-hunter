"""
State Management System for AI Hunter
Provides global, shared, and private state scopes with PostgreSQL persistence.
Inspired by LangGraph checkpointing and Redis state management patterns.
"""

import json
from typing import Any, Dict, Optional, List
from enum import Enum
from datetime import datetime, timezone
from dataclasses import dataclass, asdict

class StateScope(Enum):
    """State visibility scopes"""
    GLOBAL = "global"      # Shared across all missions (settings, quotas, etc.)
    MISSION = "mission"     # Shared within a mission (plan, findings, context)
    AGENT = "agent"        # Private to a specific agent/tool instance
    CHECKPOINT = "checkpoint"  # Snapshot for pause/resume

@dataclass
class StateSnapshot:
    """A point-in-time snapshot of state"""
    id: int
    scope: StateScope
    scope_id: str  # mission_id, agent_id, or "global"
    key: str
    value: Dict[str, Any]
    version: int
    created_at: datetime
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self):
        return {
            **asdict(self),
            'scope': self.scope.value,
            'created_at': self.created_at.isoformat()
        }

class StateManager:
    """
    Manages application state with multiple scopes and PostgreSQL persistence.
    
    Scopes:
    - GLOBAL: System-wide state (settings, global quotas)
    - MISSION: Mission-specific state (plan, progress, context)
    - AGENT: Agent/tool private state (internal counters, caches)
    - CHECKPOINT: Full state snapshots for pause/resume
    
    Features:
    - Versioning: Each state update increments version
    - History: Keep previous versions for rollback
    - Snapshots: Full state dumps for recovery
    - TTL: Automatic cleanup of old state
    """
    
    def __init__(self, db):
        """
        Args:
            db: Database instance for persistence
        """
        self.db = db
        self._cache = {}  # In-memory cache for fast reads
    
    async def get_global(self, key: str, default: Any = None) -> Any:
        """Get global state (system-wide)"""
        return await self._get(StateScope.GLOBAL, "global", key, default)
    
    async def set_global(self, key: str, value: Any, metadata: Optional[Dict] = None):
        """Set global state (system-wide)"""
        await self._set(StateScope.GLOBAL, "global", key, value, metadata)
    
    async def get_mission(self, mission_id: int, key: str, default: Any = None) -> Any:
        """Get mission-specific state"""
        return await self._get(StateScope.MISSION, str(mission_id), key, default)
    
    async def set_mission(self, mission_id: int, key: str, value: Any, metadata: Optional[Dict] = None):
        """Set mission-specific state"""
        await self._set(StateScope.MISSION, str(mission_id), key, value, metadata)
    
    async def get_agent(self, agent_id: str, key: str, default: Any = None) -> Any:
        """Get agent-private state"""
        return await self._get(StateScope.AGENT, agent_id, key, default)
    
    async def set_agent(self, agent_id: str, key: str, value: Any, metadata: Optional[Dict] = None):
        """Set agent-private state"""
        await self._set(StateScope.AGENT, agent_id, key, value, metadata)
    
    async def checkpoint(self, mission_id: int, name: str, full_state: Dict[str, Any]):
        """Create a checkpoint (snapshot) for pause/resume"""
        await self._set(
            StateScope.CHECKPOINT, 
            str(mission_id), 
            name, 
            full_state,
            metadata={"checkpoint_time": datetime.now(timezone.utc).isoformat()}
        )
    
    async def restore_checkpoint(self, mission_id: int, name: str) -> Optional[Dict[str, Any]]:
        """Restore state from a checkpoint"""
        return await self._get(StateScope.CHECKPOINT, str(mission_id), name)
    
    async def list_checkpoints(self, mission_id: int) -> List[Dict[str, Any]]:
        """List all checkpoints for a mission"""
        return await self.db.list_state_snapshots(StateScope.CHECKPOINT.value, str(mission_id))
    
    async def get_mission_state_full(self, mission_id: int) -> Dict[str, Any]:
        """Get complete mission state (all keys)"""
        return await self.db.get_state_by_scope(StateScope.MISSION.value, str(mission_id))
    
    async def clear_mission_state(self, mission_id: int):
        """Clear all mission state (cleanup after completion)"""
        await self.db.clear_state_scope(StateScope.MISSION.value, str(mission_id))
    
    # Internal methods
    async def _get(self, scope: StateScope, scope_id: str, key: str, default: Any = None) -> Any:
        """Internal: Get state with caching"""
        cache_key = f"{scope.value}:{scope_id}:{key}"
        
        # Check cache
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # Fetch from database
        value = await self.db.get_state(scope.value, scope_id, key)
        
        if value is None:
            return default
        
        # Cache and return
        self._cache[cache_key] = value
        return value
    
    async def _set(self, scope: StateScope, scope_id: str, key: str, value: Any, metadata: Optional[Dict] = None):
        """Internal: Set state with versioning"""
        # Update database
        await self.db.set_state(scope.value, scope_id, key, value, metadata)
        
        # Update cache
        cache_key = f"{scope.value}:{scope_id}:{key}"
        self._cache[cache_key] = value
    
    def invalidate_cache(self, scope: Optional[StateScope] = None, scope_id: Optional[str] = None):
        """Invalidate cache (useful for external updates)"""
        if scope is None:
            self._cache.clear()
        else:
            prefix = f"{scope.value}:{scope_id if scope_id else ''}"
            keys_to_remove = [k for k in self._cache if k.startswith(prefix)]
            for k in keys_to_remove:
                del self._cache[k]
