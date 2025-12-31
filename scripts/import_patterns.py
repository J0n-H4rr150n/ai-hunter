"""
Attack Pattern Importer

Loads attack patterns from YAML files, generates embeddings, and stores in PostgreSQL.

Usage:
    python scripts/import_patterns.py
    python scripts/import_patterns.py --pattern indirect_state_manipulation.yaml
    python scripts/import_patterns.py --clear  # Clear all patterns first
"""

import asyncio
import sys
import yaml
import argparse
from pathlib import Path
from typing import List, Dict, Any

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from core.embedding_service import LocalEmbeddingService
from backend.database import Database
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PatternImporter:
    """Imports attack patterns from YAML files into database."""
    
    def __init__(self):
        self.db: Database | None = None
        self.embedder: LocalEmbeddingService | None = None
        self.pattern_dir = Path('successful_patterns')
    
    async def initialize(self):
        """Initialize database and embedding service."""
        logger.info("[Importer] Initializing...")
        
        # Initialize database
        self.db = Database()
        await self.db.initialize()
        logger.info("[Importer] ✅ Database connected")
        
        # Initialize embedding service
        self.embedder = LocalEmbeddingService()
        logger.info("[Importer] ✅ Embedding service ready")
    
    async def clear_patterns(self):
        """Clear all existing patterns from database."""
        logger.info("[Importer] Clearing existing patterns...")
        
        async with self.db.pool.acquire() as conn:
            await conn.execute("DELETE FROM pattern_usage")
            await conn.execute("DELETE FROM pattern_indicators")
            await conn.execute("DELETE FROM pattern_steps")
            await conn.execute("DELETE FROM attack_patterns")
        
        logger.info("[Importer] ✅ All patterns cleared")
    
    def load_pattern_file(self, filepath: Path) -> Dict[str, Any]:
        """Load and parse YAML pattern file."""
        logger.info(f"[Importer] Loading: {filepath.name}")
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                pattern = yaml.safe_load(f)
            return pattern
        except Exception as e:
            logger.error(f"[Importer] ❌ Failed to load {filepath}: {e}")
            return None
    
    async def import_pattern(self, pattern: Dict[str, Any], source_file: str) -> int:
        """
        Import a single pattern into the database.
        
        Returns:
            Pattern ID if successful, None if failed
        """
        try:
            metadata = pattern.get('metadata', {})
            pattern_data = pattern.get('pattern', {})
            
            name = metadata.get('name', 'Unnamed Pattern')
            logger.info(f"[Importer] Importing: {name}")
            
            # Generate embedding
            embedding = self.embedder.embed_pattern(pattern)
            # Convert to pgvector format: '[val1,val2,val3,...]'
            embedding_str = '[' + ','.join(map(str, embedding.tolist())) + ']'
            
            # Insert or update attack_pattern record (upsert on name)
            async with self.db.pool.acquire() as conn:
                # First, try to get existing pattern ID
                existing = await conn.fetchrow(
                    "SELECT id FROM attack_patterns WHERE name = $1",
                    name
                )
                
                if existing:
                    # Update existing pattern
                    pattern_id = existing['id']
                    await conn.execute(
                        """
                        UPDATE attack_patterns
                        SET description = $1,
                            difficulty = $2,
                            tags = $3,
                            embedding = $4::vector,
                            updated_at = NOW()
                        WHERE id = $5
                        """,
                        pattern_data.get('description', ''),
                        metadata.get('difficulty', 'unknown'),
                        metadata.get('tags', []),
                        embedding_str,
                        pattern_id
                    )
                    logger.info(f"[Importer]   → Updated pattern ID: {pattern_id}")
                    
                    # Delete existing steps and indicators for re-import
                    await conn.execute("DELETE FROM pattern_steps WHERE pattern_id = $1", pattern_id)
                    await conn.execute("DELETE FROM pattern_indicators WHERE pattern_id = $1", pattern_id)
                    
                else:
                    # Insert new pattern
                    pattern_id = await conn.fetchval(
                        """
                        INSERT INTO attack_patterns (name, description, difficulty, tags, embedding)
                        VALUES ($1, $2, $3, $4, $5::vector)
                        RETURNING id
                        """,
                        name,
                        pattern_data.get('description', ''),
                        metadata.get('difficulty', 'unknown'),
                        metadata.get('tags', []),
                        embedding_str
                    )
                    logger.info(f"[Importer]   → Created pattern ID: {pattern_id}")
                
                # Insert pattern steps
                attack_sequence = pattern_data.get('attack_sequence', [])
                for step in attack_sequence:
                    await conn.execute(
                        """
                        INSERT INTO pattern_steps (pattern_id, step_number, action, tool, expected_result)
                        VALUES ($1, $2, $3, $4, $5)
                        """,
                        pattern_id,
                        step.get('step'),
                        step.get('action'),
                        step.get('tool'),
                        step.get('expected_result')
                    )
                
                logger.info(f"[Importer]   → {len(attack_sequence)} steps inserted")
                
                # Insert pattern indicators
                indicators = pattern_data.get('indicators', [])
                for indicator in indicators:
                    await conn.execute(
                        """
                        INSERT INTO pattern_indicators (pattern_id, indicator)
                        VALUES ($1, $2)
                        """,
                        pattern_id,
                        indicator
                    )
                
                logger.info(f"[Importer]   → {len(indicators)} indicators inserted")
                logger.info(f"[Importer] ✅ Successfully imported: {name}")
                
                return pattern_id
                
        except Exception as e:
            logger.error(f"[Importer] ❌ Failed to import pattern: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    async def import_all_patterns(self, specific_pattern: str = None):
        """Import all patterns from the patterns directory."""
        
        if not self.pattern_dir.exists():
            logger.error(f"[Importer] ❌ Pattern directory not found: {self.pattern_dir}")
            return
        
        # Get pattern files
        if specific_pattern:
            pattern_files = [self.pattern_dir / specific_pattern]
        else:
            pattern_files = list(self.pattern_dir.glob('*.yaml'))
            pattern_files.extend(self.pattern_dir.glob('*.yml'))
        
        if not pattern_files:
            logger.warning("[Importer] ⚠️  No pattern files found")
            return
        
        logger.info(f"[Importer] Found {len(pattern_files)} pattern file(s)")
        
        success_count = 0
        for pattern_file in pattern_files:
            pattern = self.load_pattern_file(pattern_file)
            if pattern:
                pattern_id = await self.import_pattern(pattern, pattern_file.name)
                if pattern_id:
                    success_count += 1
        
        logger.info(f"\n[Importer] ✅ Import complete: {success_count}/{len(pattern_files)} patterns imported")
    
    async def cleanup(self):
        """Clean up resources."""
        if self.db:
            await self.db.close()
        logger.info("[Importer] ✅ Cleanup complete")


async def main():
    """Main entry point for pattern importer."""
    parser = argparse.ArgumentParser(description='Import attack patterns into database')
    parser.add_argument('--pattern', help='Import specific pattern file')
    parser.add_argument('--clear', action='store_true', help='Clear existing patterns first')
    args = parser.parse_args()
    
    importer = PatternImporter()
    
    try:
        await importer.initialize()
        
        if args.clear:
            await importer.clear_patterns()
        
        await importer.import_all_patterns(args.pattern)
        
    finally:
        await importer.cleanup()


if __name__ == '__main__':
    asyncio.run(main())
