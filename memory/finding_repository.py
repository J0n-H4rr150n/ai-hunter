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
    if os.getenv('DISABLE_SEMANTIC_SEARCH', '').lower() in ('1', 'true', 'yes'):
        SEMANTIC_AVAILABLE = False
        print("[Memory] Semantic search disabled via DISABLE_SEMANTIC_SEARCH env var")
    else:
        from sentence_transformers import SentenceTransformer
        import numpy as np
        SEMANTIC_AVAILABLE = True
except ImportError:
    SEMANTIC_AVAILABLE = False
    # print("[Memory] Warning: 'sentence_transformers' or 'numpy' not found. Semantic search disabled.")

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
                # Load a lightweight model optimized for local speed
                # 'all-MiniLM-L6-v2' is a standard for efficient local embeddings
                print("[Memory] Loading semantic search model 'all-MiniLM-L6-v2'...")
                print("         (First run will download ~90MB model, may take 1-2 minutes)")
                self.embedder = SentenceTransformer('all-MiniLM-L6-v2')
                print("[Memory] ✓ Semantic search enabled")
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
        If semantic search is enabled, the embedding is generated in a 
        background thread to avoid blocking the main execution loop.
        
        Args:
            content: The actual data (dict, string, or list).
            finding_type: Category (e.g., 'credential', 'url', 'summary').
            source: Origin of the data (e.g., URL or filename).
            tags: List of descriptive tags for retrieval.
            
        Returns:
            str: The ID of the saved finding.
        """
        finding_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        
        # Organize by type to keep the file system clean
        type_dir = self.findings_dir / finding_type
        if not os.path.exists(type_dir):
            os.makedirs(type_dir, exist_ok=True)

        # Initial save without embedding (Fast)
        finding_data = {
            "id": finding_id,
            "timestamp": timestamp,
            "type": finding_type,
            "source": source,
            "tags": tags or [],
            "content": content,
            "embedding": None # Will be updated asynchronously
        }

        # Filename includes timestamp for chronological sorting in file explorer
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{finding_id[:8]}.json"
        filepath = type_dir / filename

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(finding_data, f, indent=2, ensure_ascii=False)
            
            # Trigger async embedding generation if available
            if self.embedder:
                threading.Thread(
                    target=self._generate_and_save_embedding,
                    args=(filepath, content),
                    daemon=True
                ).start()

            if Config.DEBUG:
                print(f"[Memory] Saved finding ({finding_type}): {filename}")
                
            return finding_id
        except Exception as e:
            print(f"[Memory] Failed to save finding: {e}")
            return None

    def _generate_and_save_embedding(self, filepath: Path, content: Any):
        """
        Helper method running in a background thread to generate 
        embeddings and update the JSON file.
        """
        try:
            # Prepare content string
            content_str = str(content)
            if isinstance(content, (dict, list)):
                content_str = json.dumps(content)
            
            # Generate embedding (Slow operation)
            embedding = self.embedder.encode(content_str).tolist()
            
            # Update the file
            # Note: Using simple file IO. In high concurrency, file locking might be needed.
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                data['embedding'] = embedding
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    
                if Config.DEBUG:
                    print(f"[Memory] Background embedding updated for {filepath.name}")

        except Exception as e:
            print(f"[Memory] Background embedding failed: {e}")

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
        Mimics cloud bucket search by scanning local files and comparing embeddings.
        
        Args:
            query: The natural language search query.
            limit: Max number of results to return.
            finding_type: Optional filter by category.
        """
        if not self.embedder or not SEMANTIC_AVAILABLE:
            print("[Memory] Semantic search unavailable. Install 'sentence-transformers' and 'numpy'.")
            return []

        # 1. Embed the query
        query_vec = self.embedder.encode(query)
        results = []

        # 2. Determine scan scope
        if finding_type:
            search_dirs = [self.findings_dir / finding_type]
        else:
            search_dirs = [Path(x[0]) for x in os.walk(self.findings_dir)]

        # 3. Scan files and calculate similarity
        # (For massive datasets, you'd want a vector DB, but for a local 'bucket', this is fine)
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
                    
                    # Skip if no embedding exists
                    if not data.get('embedding'):
                        continue
                        
                    # Calculate Cosine Similarity
                    doc_vec = np.array(data['embedding'])
                    
                    # Cosine Sim = (A . B) / (||A|| * ||B||)
                    norm_q = np.linalg.norm(query_vec)
                    norm_d = np.linalg.norm(doc_vec)
                    
                    if norm_q == 0 or norm_d == 0:
                        score = 0
                    else:
                        score = np.dot(query_vec, doc_vec) / (norm_q * norm_d)
                    
                    results.append((score, data))

                except Exception:
                    continue
        
        # 4. Sort by score (Highest first) and slice
        results.sort(key=lambda x: x[0], reverse=True)
        
        # Return just the data, stripping the score
        return [r[1] for r in results[:limit]]