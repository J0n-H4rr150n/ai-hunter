import json
import os
import uuid
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path
from config.config import Config

# Optional imports for semantic features
try:
    # Allow disabling semantic search via environment variable
    if os.getenv('DISABLE_EMBEDDINGS', 'true').lower() in ('1', 'true', 'yes'):
        SEMANTIC_AVAILABLE = False
        print("[Memory] Embeddings disabled via DISABLE_EMBEDDINGS env var")
    else:
        import tensorflow_hub as hub
        import tensorflow_text as text  # Required for TF2 USE model
        import numpy as np
        SEMANTIC_AVAILABLE = True
except ImportError:
    SEMANTIC_AVAILABLE = False
    # print("[Memory] Warning: 'tensorflow-hub' or 'tensorflow-text' not found. Semantic search disabled.")

class FindingRepository:
    """
    The central repository for agent discoveries.
    Stores structured findings in the hive bucket, organized by category.
    Supports local semantic search if dependencies are installed.
    """

    def __init__(self):
        # specific bucket directory for persistent findings
        self.findings_dir = Config.HIVE_BUCKET_ROOT / "findings"
        self._ensure_storage()
        
        self.embedder = None
        if SEMANTIC_AVAILABLE:
            try:
                # Load Universal Sentence Encoder from Kaggle (no Hugging Face!)
                # Model outputs 512-dimensional embeddings
                print("[Memory] Loading Universal Sentence Encoder from Kaggle...")
                print("         (First run will download ~1GB model, may take 3-5 minutes)")
                kaggle_handle = "https://www.kaggle.com/models/google/universal-sentence-encoder/tensorFlow2/universal-sentence-encoder/2?tfhub-redirect=true"
                self.embedder = hub.load(kaggle_handle)
                print("[Memory] ✓ Semantic search enabled (TensorFlow USE, 512 dims)")
            except Exception as e:
                print(f"[Memory] ⚠️  Could not load embedding model: {e}")
                print(f"[Memory] Continuing without semantic search capability")

    def _ensure_storage(self):
        """Ensures the findings directory exists."""
        if not os.path.exists(self.findings_dir):
            os.makedirs(self.findings_dir, exist_ok=True)

    def save_finding(self, content: Any, finding_type: str = "general", source: str = None, tags: List[str] = None) -> str:
        """
        Saves a new finding to the hive bucket immediately.
    def save_finding(
        self, 
        content: Any, 
        finding_type: str = "general", 
        source: str = "agent",
        tags: List[str] = None
    ) -> str:
        """
        Saves a finding to the local file-based 'bucket'.
        Deduplicates based on content hash to avoid storing identical findings.
        """
        import hashlib
        
        finding_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Create type directory
        type_dir = self.findings_dir / finding_type
        if not os.path.exists(type_dir):
            os.makedirs(type_dir, exist_ok=True)

        # Generate content hash for deduplication
        content_str = json.dumps(content, sort_keys=True) if isinstance(content, (dict, list)) else str(content)
        content_hash = hashlib.sha256(content_str.encode('utf-8')).hexdigest()[:16]
        
        # Check if this exact content already exists
        for filename in os.listdir(type_dir):
            if not filename.endswith('.json'):
                continue
            filepath = type_dir / filename
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
                existing_content_str = json.dumps(existing.get('content'), sort_keys=True) if isinstance(existing.get('content'), (dict, list)) else str(existing.get('content'))
                existing_hash = hashlib.sha256(existing_content_str.encode('utf-8')).hexdigest()[:16]
                
                if existing_hash == content_hash:
                    if Config.DEBUG:
                        print(f"[Memory] Duplicate finding detected, skipping: {finding_type}/{filename}")
                    return existing['id']  # Return existing ID instead of creating duplicate
            except Exception:
                continue

        # Save to file immediately (no embedding needed in JSON files)
        finding_data = {
            "id": finding_id,
            "timestamp": timestamp,
            "type": finding_type,
            "source": source,
            "tags": tags or [],
            "content": content,
            "content_hash": content_hash
        }

        # Filename includes timestamp for chronological sorting in file explorer
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{finding_id[:8]}.json"
        filepath = type_dir / filename

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(finding_data, f, indent=2, ensure_ascii=False)
            
            if Config.DEBUG:
                print(f"[Memory] Saved finding ({finding_type}): {filename}")
                
            return finding_id
        except Exception as e:
            print(f"[Memory] Failed to save finding: {e}")
            return None

    def get_finding(self, finding_id: str) -> Optional[Dict]:
        """
        Retrieves a specific finding by its ID.
        Iterates through type directories since ID doesn't encode type.
        """
        for root, dirs, files in os.walk(self.findings_dir):
            for file in files:
                if finding_id in file: 
                    try:
                        with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                            return json.load(f)
                    except Exception as e:
                        print(f"[Memory] Error reading finding {finding_id}: {e}")
                        return None
        return None

    def search_findings(self, tag: str = None, finding_type: str = None) -> List[Dict]:
        """
        Searches the hive for findings matching a tag or type (Exact Match).
        """
        results = []
        
        # Determine directories to search
        if finding_type:
            search_dirs = [self.findings_dir / finding_type]
        else:
            # Get all subdirectories in findings_dir
            search_dirs = [Path(x[0]) for x in os.walk(self.findings_dir)]
        
        for directory in search_dirs:
            if not os.path.exists(directory):
                continue
                
            for filename in os.listdir(directory):
                if not filename.endswith('.json'):
                    continue
                    
                filepath = os.path.join(directory, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        
                    # Filter logic
                    if tag and tag not in data.get('tags', []):
                        continue
                        
                    results.append(data)
                except Exception:
                    continue
                    
        return results

    def semantic_search(self, query: str, limit: int = 5, finding_type: str = None) -> List[Dict]:
        """
        Performs a semantic search against finding contents using vector similarity.
        
        NOTE: This method won't work anymore since embeddings are not stored in JSON files.
        Embeddings are only stored in the database for PostgreSQL-based semantic search.
        This method is kept for backwards compatibility but will return empty results.
        
        Args:
            query: The natural language search query.
            limit: Max number of results to return.
            finding_type: Optional filter by category.
        """
        print("[Memory] Warning: JSON file-based semantic search is disabled. Embeddings are not stored in files.")
        return []