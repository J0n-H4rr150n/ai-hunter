"""
Database layer for PostgreSQL with pgvector
"""

import asyncpg
import os
import json
from typing import Optional, List, Dict, Any
from datetime import datetime

class Database:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
        self.database_url = os.getenv("DATABASE_URL", "postgresql://hunter:hunter_pass_dev@postgres:5432/ai_hunter")
    
    async def initialize(self):
        """Create connection pool"""
        self.pool = await asyncpg.create_pool(self.database_url)
        print("✅ Database connection pool created")
    
    async def close(self):
        """Close connection pool"""
        if self.pool:
            await self.pool.close()
            print("👋 Database connection pool closed")
    
    async def check_connection(self) -> bool:
        """Health check"""
        try:
            async with self.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception as e:
            print(f"Database health check failed: {e}")
            return False
    
    # Mission operations
    async def create_mission(self, target_url: str, instructions: Optional[str] = None) -> int:
        """Create a new mission"""
        async with self.pool.acquire() as conn:
            mission_id = await conn.fetchval(
                """
                INSERT INTO missions (goal, target_url, instructions, status)
                VALUES ($1, $2, $3, $4)
                RETURNING id
                """,
                f"Audit {target_url}",
                target_url,
                instructions,
                "planning"
            )
        return mission_id
    
    async def update_mission_status(self, mission_id: int, status: str):
        """Update mission status"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE missions SET status = $1 WHERE id = $2",
                status, mission_id
            )
    
    async def update_mission_plan(self, mission_id: int, plan: dict, approved: bool = False):
        """Update mission plan"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE missions SET plan = $1 WHERE id = $2",
                json.dumps(plan), mission_id
            )
            if approved:
                await conn.execute(
                    "UPDATE missions SET status = $1 WHERE id = $2",
                    "approved", mission_id
                )
    
    async def get_mission(self, mission_id: int) -> Optional[Dict[str, Any]]:
        """Get mission by ID"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM missions WHERE id = $1",
                mission_id
            )
            if row:
                return dict(row)
        return None
    
    async def list_missions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List recent missions"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM missions ORDER BY created_at DESC LIMIT $1",
                limit
            )
            return [dict(row) for row in rows]
    
    # Finding operations
    async def save_finding(
        self,
        mission_id: int,
        content: dict,
        finding_type: str,
        source: str,
        tags: List[str],
        embedding: Optional[List[float]] = None
    ) -> int:
        """Save a finding with optional vector embedding"""
        async with self.pool.acquire() as conn:
            finding_id = await conn.fetchval(
                """
                INSERT INTO findings (mission_id, content, finding_type, source, tags, embedding)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                mission_id,
                json.dumps(content),
                finding_type,
                source,
                tags,
                embedding
            )
        return finding_id
    
    async def search_findings_by_vector(
        self,
        query_embedding: List[float],
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Semantic search using pgvector"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, content, finding_type, source, tags,
                       1 - (embedding <=> $1) as similarity
                FROM findings
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> $1
                LIMIT $2
                """,
                query_embedding,
                limit
            )
            return [dict(row) for row in rows]
    
    async def get_mission_findings(self, mission_id: int) -> List[Dict[str, Any]]:
        """Get all findings for a mission"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM findings WHERE mission_id = $1 ORDER BY created_at DESC",
                mission_id
            )
            return [dict(row) for row in rows]
    
    # Agent action logging
    async def log_action(
        self,
        mission_id: int,
        action_type: str,
        action_data: dict,
        screenshot_path: Optional[str] = None
    ):
        """Log an agent action"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO agent_actions (mission_id, action_type, action_data, screenshot_path)
                VALUES ($1, $2, $3, $4)
                """,
                mission_id,
                action_type,
                json.dumps(action_data),
                screenshot_path
            )
    
    async def save_llm_trace(self, trace) -> int:
        """Save LLM trace for observability"""
        trace_dict = trace.to_dict()
        
        async with self.pool.acquire() as conn:
            trace_id = await conn.fetchval(
                """
                INSERT INTO llm_traces (
                    trace_id, parent_trace_id, session_id, mission_id,
                    llm_model, llm_provider, temperature, top_p, max_tokens,
                    system_prompt, user_prompt, conversation_history,
                    input_tokens, input_characters,
                    llm_response, llm_reasoning, llm_decision, llm_confidence,
                    output_tokens, output_characters,
                    timestamp_start, timestamp_end, elapsed_time_ms, tokens_per_second,
                    safety_scores, safety_blocked, finish_reason,
                    estimated_cost_usd, request_id,
                    status, error_message, retry_count, fallback_used,
                    agent_name, agent_state_before, agent_state_after,
                    tools_available, tools_called, memory_retrieved,
                    raw_request, raw_response, environment
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                    $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26,
                    $27, $28, $29, $30, $31, $32, $33, $34, $35, $36, $37, $38,
                    $39, $40, $41
                )
                RETURNING id
                """,
                trace_dict.get('trace_id'),
                trace_dict.get('parent_trace_id'),
                trace_dict.get('session_id'),
                trace_dict.get('mission_id'),
                trace_dict.get('llm_model'),
                trace_dict.get('llm_provider'),
                trace_dict.get('temperature'),
                trace_dict.get('top_p'),
                trace_dict.get('max_tokens'),
                trace_dict.get('system_prompt'),
                trace_dict.get('user_prompt'),
                json.dumps(trace_dict.get('conversation_history')) if trace_dict.get('conversation_history') else None,
                trace_dict.get('input_tokens'),
                trace_dict.get('input_characters'),
                trace_dict.get('llm_response'),
                trace_dict.get('llm_reasoning'),
                trace_dict.get('llm_decision'),
                trace_dict.get('llm_confidence'),
                trace_dict.get('output_tokens'),
                trace_dict.get('output_characters'),
                trace_dict.get('timestamp_start'),
                trace_dict.get('timestamp_end'),
                trace_dict.get('elapsed_time_ms'),
                trace_dict.get('tokens_per_second'),
                json.dumps(trace_dict.get('safety_scores')) if trace_dict.get('safety_scores') else None,
                trace_dict.get('safety_blocked', False),
                trace_dict.get('finish_reason'),
                trace_dict.get('estimated_cost_usd'),
                trace_dict.get('request_id'),
                trace_dict.get('status'),
                trace_dict.get('error_message'),
                trace_dict.get('retry_count', 0),
                trace_dict.get('fallback_used', False),
                trace_dict.get('agent_name'),
                json.dumps(trace_dict.get('agent_state_before')) if trace_dict.get('agent_state_before') else None,
                json.dumps(trace_dict.get('agent_state_after')) if trace_dict.get('agent_state_after') else None,
                trace_dict.get('tools_available'),
                trace_dict.get('tools_called'),
                json.dumps(trace_dict.get('memory_retrieved')) if trace_dict.get('memory_retrieved') else None,
                json.dumps(trace_dict.get('raw_request')) if trace_dict.get('raw_request') else None,
                json.dumps(trace_dict.get('raw_response')) if trace_dict.get('raw_response') else None,
                trace_dict.get('environment', 'development')
            )
        return trace_id
