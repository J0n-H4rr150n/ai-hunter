"""
Pattern Search Service

Provides semantic search over attack patterns using vector embeddings.
"""

import asyncio
from typing import List, Dict, Any, Optional
import logging
import numpy as np

from backend.database import Database
from core.embedding_service import get_embedding_service, LocalEmbeddingService

logger = logging.getLogger(__name__)


class PatternSearchService:
    """
    Search for relevant attack patterns using semantic similarity.
    
    Uses vector embeddings to find patterns that match the current context,
    even if exact keywords don't match.
    """
    
    def __init__(self, db: Database, embedder: LocalEmbeddingService = None):
        """
        Initialize pattern search service.
        
        Args:
            db: Database instance
            embedder: Optional embedding service (creates default if not provided)
        """
        self.db = db
        self.embedder = embedder or get_embedding_service()
    
    async def search_patterns(
        self,
        query: str,
        findings: Dict[str, Any] = None,
        tags: List[str] = None,
        top_k: int = 3,
        similarity_threshold: float = 0.5
    ) -> List[Dict[str, Any]]:
        """
        Search for relevant attack patterns.
        
        Args:
            query: Natural language description of the situation
            findings: Current mission findings (endpoints, behaviors, etc.)
            tags: Optional filter by tags
            top_k: Number of results to return
            similarity_threshold: Minimum similarity score (0-1)
            
        Returns:
            List of pattern dictionaries with similarity scores
        """
        logger.info(f"[PatternSearch] Searching for: {query[:100]}...")
        
        # Build comprehensive search query
        search_text = self._build_search_query(query, findings)
        logger.debug(f"[PatternSearch] Full query: {search_text}")
        
        # Generate query embedding
        query_embedding = self.embedder.embed_text(search_text)
        
        # Search database
        patterns = await self._vector_search(
            embedding=query_embedding,
            tags=tags,
            top_k=top_k,
            threshold=similarity_threshold
        )
        
        logger.info(f"[PatternSearch] Found {len(patterns)} relevant patterns")
        
        # Enrich with steps and indicators
        enriched_patterns = []
        for pattern in patterns:
            enriched = await self._enrich_pattern(pattern)
            enriched_patterns.append(enriched)
        
        return enriched_patterns
    
    def _build_search_query(self, query: str, findings: Dict[str, Any] = None) -> str:
        """
        Build comprehensive search query from user query and findings.
        
        Combines:
        - User's natural language query
        - Discovered endpoints
        - Observed behaviors
        - Error messages
        - Response patterns
        """
        query_parts = [query]
        
        if not findings:
            return query
        
        # Add endpoint information
        if 'endpoints' in findings:
            endpoints = findings['endpoints']
            if isinstance(endpoints, list):
                query_parts.append(f"Endpoints: {', '.join(endpoints[:10])}")
        
        # Add observed behaviors
        if 'behaviors' in findings:
            behaviors = findings['behaviors']
            if isinstance(behaviors, list):
                query_parts.append(f"Behaviors: {', '.join(behaviors)}")
        
        # Add error patterns
        if 'errors' in findings:
            errors = findings['errors']
            if isinstance(errors, list):
                query_parts.append(f"Errors: {', '.join(errors[:5])}")
        
        # Add response codes
        if 'response_codes' in findings:
            codes = findings['response_codes']
            if isinstance(codes, dict):
                code_summary = ', '.join([f"{k}:{v}" for k, v in list(codes.items())[:5]])
                query_parts.append(f"Response codes: {code_summary}")
        
        # Add parameter patterns
        if 'parameters' in findings:
            params = findings['parameters']
            if isinstance(params, list):
                query_parts.append(f"Parameters: {', '.join(params[:10])}")
        
        return ' | '.join(query_parts)
    
    async def _vector_search(
        self,
        embedding: np.ndarray,
        tags: List[str] = None,
        top_k: int = 3,
        threshold: float = 0.5
    ) -> List[Dict[str, Any]]:
        """
        Perform vector similarity search in PostgreSQL.
        
        Uses pgvector's <=> operator for cosine distance.
        """
        # Convert to pgvector string format
        embedding_str = '[' + ','.join(map(str, embedding.tolist())) + ']'
        
        async with self.db.pool.acquire() as conn:
            # Build query with optional tag filter
            if tags:
                query = """
                    SELECT 
                        id, name, description, difficulty, tags,
                        1 - (embedding <=> $1::vector) as similarity
                    FROM attack_patterns
                    WHERE tags && $2::text[]  -- Tag overlap
                      AND 1 - (embedding <=> $1::vector) >= $3
                    ORDER BY embedding <=> $1::vector
                    LIMIT $4
                """
                rows = await conn.fetch(query, embedding_str, tags, threshold, top_k)
            else:
                query = """
                    SELECT 
                        id, name, description, difficulty, tags,
                        1 - (embedding <=> $1::vector) as similarity
                    FROM attack_patterns
                    WHERE 1 - (embedding <=> $1::vector) >= $2
                    ORDER BY embedding <=> $1::vector
                    LIMIT $3
                """
                rows = await conn.fetch(query, embedding_str, threshold, top_k)
            
            return [dict(row) for row in rows]
    
    async def _enrich_pattern(self, pattern: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enrich pattern with steps and indicators.
        
        Args:
            pattern: Pattern from database
            
        Returns:
            Pattern with 'steps' and 'indicators' added
        """
        pattern_id = pattern['id']
        
        async with self.db.pool.acquire() as conn:
            # Get steps
            steps = await conn.fetch(
                """
                SELECT step_number, action, tool, expected_result
                FROM pattern_steps
                WHERE pattern_id = $1
                ORDER BY step_number
                """,
                pattern_id
            )
            pattern['steps'] = [dict(step) for step in steps]
            
            # Get indicators
            indicators = await conn.fetch(
                """
                SELECT indicator
                FROM pattern_indicators
                WHERE pattern_id = $1
                """,
                pattern_id
            )
            pattern['indicators'] = [row['indicator'] for row in indicators]
        
        return pattern
    
    async def record_pattern_usage(
        self,
        pattern_id: int,
        mission_id: int,
        iteration_id: int = None,
        was_successful: bool = False
    ):
        """Record that a pattern was used in a mission."""
        async with self.db.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO pattern_usage (pattern_id, mission_id, iteration_id, was_successful)
                VALUES ($1, $2, $3, $4)
                """,
                pattern_id, mission_id, iteration_id, was_successful
            )
            
            # Increment success count if successful
            if was_successful:
                await conn.execute(
                    """
                    UPDATE attack_patterns
                    SET success_count = success_count + 1
                    WHERE id = $1
                    """,
                    pattern_id
                )
    
    async def get_pattern_by_id(self, pattern_id: int) -> Optional[Dict[str, Any]]:
        """Get full pattern details by ID."""
        async with self.db.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, name, description, difficulty, tags, success_count
                FROM attack_patterns
                WHERE id = $1
                """,
                pattern_id
            )
            
            if not row:
                return None
            
            pattern = dict(row)
            return await self._enrich_pattern(pattern)
