"""
Comprehensive LLM observability and tracing wrapper
Captures everything needed for debugging, auditing, and optimization
"""

import time
import json
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from enum import Enum

class LLMCallStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    SAFETY_BLOCKED = "safety_blocked"

@dataclass
class LLMTrace:
    """Complete trace of an LLM API call"""
    
    # Identifiers
    trace_id: str
    parent_trace_id: Optional[str] = None
    session_id: Optional[str] = None
    mission_id: Optional[int] = None
    
    # Model Configuration
    llm_model: str = None
    llm_provider: str = "local_llama"  # local_llama (llama-server), openai, anthropic, etc.
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    
    # Input
    system_prompt: Optional[str] = None
    user_prompt: str = None
    conversation_history: Optional[List[Dict]] = None
    input_tokens: Optional[int] = None
    input_characters: Optional[int] = None
    
    # Output
    llm_response: Optional[str] = None
    llm_reasoning: Optional[str] = None  # Chain of thought
    llm_decision: Optional[str] = None  # What the agent decided to do
    llm_confidence: Optional[float] = None  # 0.0 to 1.0
    output_tokens: Optional[int] = None
    output_characters: Optional[int] = None
    
    # Performance
    timestamp_start: str = None
    timestamp_end: str = None
    elapsed_time_ms: Optional[int] = None
    tokens_per_second: Optional[float] = None
    
    # Quality & Safety
    safety_scores: Optional[Dict[str, float]] = None  # e.g., {"harassment": 0.1, "hate": 0.05}
    safety_blocked: bool = False
    finish_reason: Optional[str] = None  # "stop", "length", "safety", etc.
    
    # Cost & Usage
    estimated_cost_usd: Optional[float] = None
    request_id: Optional[str] = None  # Provider's request ID
    
    # Error Handling
    status: str = LLMCallStatus.SUCCESS.value
    error_message: Optional[str] = None
    retry_count: int = 0
    fallback_used: bool = False
    
    # Agent Context
    agent_name: Optional[str] = None
    agent_state_before: Optional[Dict] = None
    agent_state_after: Optional[Dict] = None
    tools_available: Optional[List[str]] = None
    tools_called: Optional[List[str]] = None
    memory_retrieved: Optional[List[Dict]] = None
    
    # Debugging
    raw_request: Optional[Dict] = None
    raw_response: Optional[Dict] = None
    environment: str = "development"  # development, staging, production
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        return {k: v for k, v in asdict(self).items() if v is not None}
    
    def calculate_derived_metrics(self):
        """Calculate derived metrics"""
        if self.timestamp_start and self.timestamp_end:
            start = datetime.fromisoformat(self.timestamp_start)
            end = datetime.fromisoformat(self.timestamp_end)
            self.elapsed_time_ms = int((end - start).total_seconds() * 1000)
        
        if self.output_tokens and self.elapsed_time_ms:
            self.tokens_per_second = (self.output_tokens / self.elapsed_time_ms) * 1000
        
        if self.user_prompt:
            self.input_characters = len(self.user_prompt)
        
        if self.llm_response:
            self.output_characters = len(self.llm_response)

class LLMTracer:
    """Manages LLM tracing and storage"""
    
    def __init__(self, database=None, redis_manager=None):
        self.database = database
        self.redis = redis_manager
    
    async def start_trace(
        self,
        agent_name: str,
        llm_model: str,
        user_prompt: str,
        trace_id: str,
        mission_id: Optional[int] = None,
        **kwargs
    ) -> LLMTrace:
        """Start a new trace"""
        trace = LLMTrace(
            trace_id=trace_id,
            mission_id=mission_id,
            agent_name=agent_name,
            llm_model=llm_model,
            user_prompt=user_prompt,
            timestamp_start=datetime.now(timezone.utc).isoformat(),
            **kwargs
        )
        return trace
    
    async def end_trace(
        self,
        trace: LLMTrace,
        llm_response: str,
        **kwargs
    ):
        """Complete the trace and store it"""
        trace.timestamp_end = datetime.now(timezone.utc).isoformat()
        trace.llm_response = llm_response
        
        # Update with any additional fields
        for key, value in kwargs.items():
            if hasattr(trace, key):
                setattr(trace, key, value)
        
        # Calculate derived metrics
        trace.calculate_derived_metrics()
        
        # Store in database
        if self.database:
            await self.database.save_llm_trace(trace)
        
        # Publish to Redis for real-time monitoring
        if self.redis and trace.mission_id:
            await self.redis.publish_mission_event(
                trace.mission_id,
                "llm_trace",
                {
                    "trace_id": trace.trace_id,
                    "agent": trace.agent_name,
                    "model": trace.llm_model,
                    "elapsed_ms": trace.elapsed_time_ms,
                    "confidence": trace.llm_confidence,
                    "decision": trace.llm_decision,
                    "timestamp": trace.timestamp_end
                }
            )
        
        return trace
    
    async def trace_error(
        self,
        trace: LLMTrace,
        error: Exception,
        retry_count: int = 0,
        fallback_used: bool = False
    ):
        """Record an error in the trace"""
        trace.timestamp_end = datetime.now(timezone.utc).isoformat()
        trace.status = LLMCallStatus.FAILED.value
        trace.error_message = str(error)
        trace.retry_count = retry_count
        trace.fallback_used = fallback_used
        trace.calculate_derived_metrics()
        
        if self.database:
            await self.database.save_llm_trace(trace)
        
        return trace


# Cost estimation (approximate, per token).
# Locally served models are free to run, so they are deliberately absent here and
# fall through to 0.0 — token counts are still recorded for context budgeting.
LLM_COSTS = {
    "gpt-4": {"input": 0.00003, "output": 0.00006},
    "gpt-3.5-turbo": {"input": 0.0000015, "output": 0.000002},
}

def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate API call cost in USD. Local models cost nothing and return 0.0."""
    if model not in LLM_COSTS:
        return 0.0

    costs = LLM_COSTS[model]
    return (input_tokens * costs["input"]) + (output_tokens * costs["output"])
