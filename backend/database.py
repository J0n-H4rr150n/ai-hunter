"""
Database layer for PostgreSQL with pgvector
"""

import asyncpg
import os
import json
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

# Check if embeddings are disabled
EMBEDDINGS_ENABLED = os.getenv('DISABLE_EMBEDDINGS', 'true').lower() not in ('1', 'true', 'yes')

class Database:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
        self.database_url = os.getenv("DATABASE_URL", "postgresql://hunter:hunter_pass_dev@postgres:5432/ai_hunter")
    
    async def initialize(self):
        """Create connection pool"""

        async def _init_connection(conn):
            # asyncpg hands back json/jsonb as raw text unless told otherwise, so
            # callers that reasonably expect dicts and lists got strings instead.
            # A non-empty JSON string is truthy, which silently inverted boolean
            # settings such as hitl_enabled.
            #
            # Most call sites here already json.dumps() their value before binding
            # it, so the encoder must pass pre-serialized text straight through or
            # it would encode a second time and store a JSON string containing JSON.
            def _encode(value):
                return value if isinstance(value, str) else json.dumps(value)

            for pg_type in ("json", "jsonb"):
                await conn.set_type_codec(
                    pg_type,
                    encoder=_encode,
                    decoder=json.loads,
                    schema="pg_catalog",
                )

        self.pool = await asyncpg.create_pool(self.database_url, init=_init_connection)
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
    
    # Settings operations
    async def get_settings(self, mission_id: Optional[int] = None) -> Dict[str, Any]:
        """Get settings (mission-specific or global)"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT key, value FROM settings WHERE mission_id IS NULL OR mission_id = $1",
                mission_id
            )
            settings = {}
            for row in rows:
                settings[row['key']] = row['value']
            return settings
    
    async def update_setting(self, key: str, value: Any, mission_id: Optional[int] = None):
        """Update a setting"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO settings (mission_id, key, value)
                VALUES ($1, $2, $3)
                ON CONFLICT (mission_id, key) 
                DO UPDATE SET value = $3, updated_at = CURRENT_TIMESTAMP
                """,
                mission_id, key, json.dumps(value)
            )
    
    # Tool approval operations
    async def save_tool_approval(
        self,
        mission_id: int,
        tool_name: str,
        tool_inputs: dict,
        approved: bool,
        context: Optional[dict] = None,
        feedback: Optional[str] = None,
        edited_inputs: Optional[dict] = None,
        response_time_ms: Optional[int] = None
    ) -> int:
        """Save a tool approval decision with embedding"""
        # Generate embedding from context + feedback for RAG (if enabled)
        embedding = None
        if EMBEDDINGS_ENABLED and (feedback or context):
            try:
                embedding_vector = await self._generate_approval_embedding(tool_name, tool_inputs, context, feedback, approved)
                # Convert list to pgvector string format: '[0.1, 0.2, 0.3]'
                embedding = '[' + ','.join(map(str, embedding_vector)) + ']'
            except Exception as e:
                print(f"Failed to generate embedding: {e}")
        
        async with self.pool.acquire() as conn:
            approval_id = await conn.fetchval(
                """
                INSERT INTO tool_approvals 
                (mission_id, tool_name, tool_inputs, context, approved, feedback, edited_inputs, response_time_ms, embedding)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING id
                """,
                mission_id, tool_name, json.dumps(tool_inputs), 
                json.dumps(context) if context else None,
                approved, feedback,
                json.dumps(edited_inputs) if edited_inputs else None,
                response_time_ms,
                embedding
            )
        return approval_id
    
    async def _generate_approval_embedding(self, tool_name: str, tool_inputs: dict, context: Optional[dict], feedback: Optional[str], approved: bool) -> List[float]:
        """Generate embedding for tool approval using TensorFlow Universal Sentence Encoder"""
        try:
            import tensorflow_hub as hub
            import tensorflow_text as text
            import numpy as np
            
            # Load model (cached after first load)
            kaggle_handle = "https://www.kaggle.com/models/google/universal-sentence-encoder/tensorFlow2/universal-sentence-encoder/2?tfhub-redirect=true"
            model = hub.load(kaggle_handle)
            
            # Construct text for embedding
            text_parts = [
                f"Tool: {tool_name}",
                f"Decision: {'approved' if approved else 'rejected'}",
            ]
            
            if tool_inputs:
                text_parts.append(f"Inputs: {json.dumps(tool_inputs)}")
            
            if context:
                text_parts.append(f"Context: {json.dumps(context)}")
            
            if feedback:
                text_parts.append(f"Feedback: {feedback}")
            
            text_to_embed = " | ".join(text_parts)
            
            # Generate embedding (Universal Sentence Encoder produces 512-dimensional vectors)
            embeddings = model([text_to_embed])
            vector = np.array(embeddings[0]).tolist()
            
            return vector
            
        except Exception as e:
            print(f"Error generating embedding: {e}")
            raise
    
    async def search_similar_approvals(self, tool_name: str, tool_inputs: dict, context: Optional[dict], limit: int = 5) -> List[Dict[str, Any]]:
        """Search for similar past tool approvals using vector similarity"""
        if not EMBEDDINGS_ENABLED:
            return []
        
        try:
            # Generate embedding for the query
            query_embedding = await self._generate_approval_embedding(tool_name, tool_inputs, context, None, True)
            
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, tool_name, tool_inputs, context, approved, feedback, 
                           embedding <=> $1::vector AS distance
                    FROM tool_approvals
                    WHERE tool_name = $2 AND embedding IS NOT NULL
                    ORDER BY embedding <=> $1::vector
                    LIMIT $3
                    """,
                    query_embedding, tool_name, limit
                )
                return [dict(row) for row in rows]
        except Exception as e:
            print(f"Error searching similar approvals: {e}")
            return []
    
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
    
    # State Management operations
    async def get_state(self, scope: str, scope_id: str, key: str) -> Optional[Any]:
        """Get state value by scope, scope_id, and key"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT value, version
                FROM state_snapshots
                WHERE scope = $1 AND scope_id = $2 AND key = $3
                ORDER BY version DESC
                LIMIT 1
                """,
                scope, scope_id, key
            )
            return row['value'] if row else None
    
    async def set_state(self, scope: str, scope_id: str, key: str, value: Any, metadata: Optional[Dict] = None):
        """Set state value with versioning"""
        async with self.pool.acquire() as conn:
            # Get current version
            current_version = await conn.fetchval(
                """
                SELECT COALESCE(MAX(version), 0)
                FROM state_snapshots
                WHERE scope = $1 AND scope_id = $2 AND key = $3
                """,
                scope, scope_id, key
            )
            
            new_version = current_version + 1
            
            # Insert new version
            await conn.execute(
                """
                INSERT INTO state_snapshots 
                (scope, scope_id, key, value, version, metadata, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                scope, scope_id, key,
                json.dumps(value) if not isinstance(value, str) else value,
                new_version,
                json.dumps(metadata) if metadata else None,
                datetime.now(timezone.utc)
            )
    
    async def get_state_by_scope(self, scope: str, scope_id: str) -> Dict[str, Any]:
        """Get all state keys for a scope"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (key) key, value, version
                FROM state_snapshots
                WHERE scope = $1 AND scope_id = $2
                ORDER BY key, version DESC
                """,
                scope, scope_id
            )
            return {row['key']: row['value'] for row in rows}
    
    async def list_state_snapshots(self, scope: str, scope_id: str) -> List[Dict[str, Any]]:
        """List all state snapshots for a scope (e.g., all checkpoints)"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, scope, scope_id, key, version, metadata, created_at
                FROM state_snapshots
                WHERE scope = $1 AND scope_id = $2
                ORDER BY created_at DESC
                """,
                scope, scope_id
            )
            return [dict(row) for row in rows]
    
    async def clear_state_scope(self, scope: str, scope_id: str):
        """Clear all state for a scope (cleanup)"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM state_snapshots
                WHERE scope = $1 AND scope_id = $2
                """,
                scope, scope_id
            )
    
    # Iteration operations
    async def create_iteration(
        self, 
        mission_id: int, 
        iteration_number: int, 
        plan: dict
    ) -> int:
        """Create a new iteration for a mission"""
        async with self.pool.acquire() as conn:
            iteration_id = await conn.fetchval(
                """
                INSERT INTO iterations (mission_id, iteration_number, plan, status)
                VALUES ($1, $2, $3, $4)
                RETURNING id
                """,
                mission_id, iteration_number, json.dumps(plan), "pending"
            )
            
            # Update mission's current iteration and total count
            await conn.execute(
                """
                UPDATE missions 
                SET current_iteration_id = $1, total_iterations = $2
                WHERE id = $3
                """,
                iteration_id, iteration_number, mission_id
            )
            
        return iteration_id
    
    async def get_iteration(self, iteration_id: int) -> Optional[Dict[str, Any]]:
        """Get iteration by ID"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM iterations WHERE id = $1",
                iteration_id
            )
            if row:
                result = dict(row)
                if result.get('plan'):
                    result['plan'] = json.loads(result['plan']) if isinstance(result['plan'], str) else result['plan']
                return result
        return None
    
    async def get_iterations_for_mission(self, mission_id: int) -> List[Dict[str, Any]]:
        """Get all iterations for a mission, ordered by iteration_number"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM iterations WHERE mission_id = $1 ORDER BY iteration_number ASC",
                mission_id
            )
            results = []
            for row in rows:
                result = dict(row)
                if result.get('plan'):
                    result['plan'] = json.loads(result['plan']) if isinstance(result['plan'], str) else result['plan']
                results.append(result)
            return results
    
    async def update_iteration_status(
        self, 
        iteration_id: int, 
        status: str,
        findings_summary: Optional[str] = None
    ):
        """Update iteration status and optionally set findings summary"""
        async with self.pool.acquire() as conn:
            if status == "in_progress":
                await conn.execute(
                    """
                    UPDATE iterations 
                    SET status = $1, started_at = NOW()
                    WHERE id = $2
                    """,
                    status, iteration_id
                )
            elif status == "completed":
                await conn.execute(
                    """
                    UPDATE iterations 
                    SET status = $1, completed_at = NOW(), findings_summary = $2
                    WHERE id = $3
                    """,
                    status, findings_summary, iteration_id
                )
            else:
                await conn.execute(
                    "UPDATE iterations SET status = $1 WHERE id = $2",
                    status, iteration_id
                )
    
    async def get_mission_iterations(self, mission_id: int) -> List[dict]:
        """Get all iterations for a mission (for LLM context)"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, iteration_number, plan, status, findings_summary, 
                       created_at, started_at, completed_at
                FROM iterations
                WHERE mission_id = $1
                ORDER BY iteration_number ASC
                """,
                mission_id
            )
            return [dict(row) for row in rows]
    
    async def get_all_iteration_summaries(self, mission_id: int) -> str:
        """Get concatenated summaries of all completed iterations"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT iteration_number, findings_summary 
                FROM iterations 
                WHERE mission_id = $1 AND status = 'completed' AND findings_summary IS NOT NULL
                ORDER BY iteration_number ASC
                """,
                mission_id
            )
            
            summaries = []
            for row in rows:
                summaries.append(f"Iteration {row['iteration_number']}:\n{row['findings_summary']}\n")
            
            return "\n".join(summaries) if summaries else "No completed iterations yet."
    
    # Activity log operations
    async def save_activity_log(
        self,
        mission_id: int,
        message: str,
        message_type: str = 'log',
        screenshot_path: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> int:
        """Save an activity feed message to database"""
        async with self.pool.acquire() as conn:
            log_id = await conn.fetchval(
                """
                INSERT INTO activity_logs 
                (mission_id, message, message_type, screenshot_path, metadata)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                mission_id, message, message_type, screenshot_path,
                json.dumps(metadata) if metadata else None
            )
        return log_id
    
    async def get_mission_activity_logs(
        self, 
        mission_id: int,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Get all activity logs for a mission"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, message, message_type, screenshot_path, 
                       metadata, timestamp
                FROM activity_logs
                WHERE mission_id = $1
                ORDER BY timestamp ASC
                LIMIT $2
                """,
                mission_id, limit
            )
            results = []
            for row in rows:
                result = dict(row)
                if result.get('metadata'):
                    result['metadata'] = json.loads(result['metadata']) if isinstance(result['metadata'], str) else result['metadata']
                results.append(result)
            return results
