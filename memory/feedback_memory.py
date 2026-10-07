import json
import time
import os
import glob
import logging
import numpy as np
from typing import List, Dict, Tuple, Optional

# Optional imports for embeddings
EMBEDDINGS_ENABLED = os.getenv('DISABLE_EMBEDDINGS', 'true').lower() not in ('1', 'true', 'yes')

if EMBEDDINGS_ENABLED:
    try:
        import tensorflow_hub as hub
        import tensorflow_text as text  # Required for TF2 USE model
        print("[FeedbackMemory] Embeddings enabled via TensorFlow USE")
    except ImportError:
        EMBEDDINGS_ENABLED = False
        print("[FeedbackMemory] Warning: TensorFlow Hub not available, embeddings disabled")
else:
    print("[FeedbackMemory] Embeddings disabled via DISABLE_EMBEDDINGS env var")

logger = logging.getLogger(__name__)


class FeedbackMemory:
    def __init__(self, project_id: str = None, base_path=None):
        self.model = None
        
        if EMBEDDINGS_ENABLED:
            try:
                # Load Universal Sentence Encoder from Kaggle (512 dimensions)
                print("[FeedbackMemory] Loading Universal Sentence Encoder from Kaggle...")
                kaggle_handle = "https://www.kaggle.com/models/google/universal-sentence-encoder/tensorFlow2/universal-sentence-encoder/2?tfhub-redirect=true"
                self.model = hub.load(kaggle_handle)
                print("[FeedbackMemory] ✓ TensorFlow USE embedding model loaded (512 dims)")
            except Exception as e:
                print(f"[FeedbackMemory] ⚠️  Failed to load embedding model: {e}")
                print("[FeedbackMemory] Continuing without embeddings")
        
        # 1. Hive Storage Configuration
        # Consistent cross-platform path: ~/ai-hunter/hive
        if base_path is None:
            # os.path.expanduser("~") gets the user's home dir on Windows/Linux/Mac
            # os.path.join handles the slashes (\ or /) correctly
            self.base_path = os.path.join(os.path.expanduser("~"), "ai-hunter", "hive")
        else:
            self.base_path = os.path.expanduser(base_path)

        self.table_path = os.path.join(self.base_path, "table=feedback")
        
        # 2. In-Memory Cache (The "RAM Drive" for Vector Search)
        # Since we use files, we load them into RAM on startup for fast RAG
        self.memory_cache: List[Dict] = []
        self.vector_cache: Optional[np.ndarray] = None
        
        # Config
        self.similarity_threshold = 0.92
        self.decay_factor = 0.1
        
        # Load existing data from disk immediately
        self._hydrate_memory()

    def _hydrate_memory(self):
        """
        Scans the Hive directory structure and loads all JSONL data into RAM.
        Structure: ~/ai-hunter/hive/table=feedback/tool=*/data.jsonl
        """
        print(f"[Memory] Hydrating from {self.table_path}...")
        self.memory_cache = []
        vectors = []
        
        if not os.path.exists(self.table_path):
            return

        # Glob for all partitions
        pattern = os.path.join(self.table_path, "tool=*", "*.jsonl")
        files = glob.glob(pattern)
        
        loaded_count = 0
        for fpath in files:
            try:
                with open(fpath, 'r') as f:
                    for line in f:
                        if line.strip():
                            record = json.loads(line)
                            # Ensure embedding is a list, not None
                            if record.get('embedding'):
                                self.memory_cache.append(record)
                                vectors.append(record['embedding'])
                                loaded_count += 1
            except Exception as e:
                print(f"[Memory] Failed to load partition {fpath}: {e}")

        if vectors:
            self.vector_cache = np.array(vectors)
            print(f"[Memory] Hydration Complete. Loaded {loaded_count} lessons.")
        else:
            self.vector_cache = None

    def _get_embedding(self, text: str) -> List[float]:
        if not self.model:
            return None  # Return None when embeddings disabled
        try:
            # TensorFlow USE returns tensor, convert to list
            return np.array(self.model([text])[0]).tolist()
        except Exception as e:
            logger.warning("embedding failed, semantic recall degraded: %s", e, exc_info=True)
            return None 

    def store_feedback(self, tool: str, thought: str, action_val: str, rating: float, reason: str):
        """
        Writes feedback to a Hive-partitioned JSONL file.
        Path: table=feedback/tool={tool}/data.jsonl
        """
        # 1. Generate Embedding (if enabled)
        new_vec = None
        if self.model:
            vector_text = f"{tool} {thought} {reason}"
            new_vec = self._get_embedding(vector_text)
        
        timestamp = time.time()
        
        record = {
            "id": f"mem_{int(timestamp*1000)}",
            "timestamp": timestamp,
            "tool": tool,
            "thought": thought,
            "proposed_value": str(action_val),
            "rating": rating,
            "human_critique": reason,
            "embedding": new_vec
        }

        # 2. Check for Duplicates (In-Memory Check) - only if embeddings enabled
        if new_vec and self.vector_cache is not None and len(self.vector_cache) > 0:
            # Cosine Sim logic
            sims = np.dot(self.vector_cache, new_vec) / (
                np.linalg.norm(self.vector_cache, axis=1) * np.linalg.norm(new_vec)
            )
            best_idx = np.argmax(sims)
            
            if sims[best_idx] > self.similarity_threshold:
                print(f"[Memory] Duplicate lesson detected (Sim: {sims[best_idx]:.2f}). Skipping write.")
                # In a file system, updates are expensive (rewrite whole file).
                # For this architecture, we skip updates to keep it fast append-only.
                return

        # 3. Write to Disk (Hive Partition)
        partition_dir = os.path.join(self.table_path, f"tool={tool}")
        os.makedirs(partition_dir, exist_ok=True)
        
        file_path = os.path.join(partition_dir, "data.jsonl")
        
        with open(file_path, "a") as f:
            f.write(json.dumps(record) + "\n")
            
        # 4. Update In-Memory Cache (So we can RAG it immediately)
        self.memory_cache.append(record)
        if new_vec:  # Only update vector cache if embedding was generated
            if self.vector_cache is None:
                self.vector_cache = np.array([new_vec])
            else:
                self.vector_cache = np.vstack([self.vector_cache, new_vec])
            
        print(f"[Memory] Saved lesson to local Hive: {file_path}")

    def retrieve_relevant_lessons(self, current_thought: str, current_tool: str, limit=3) -> str:
        """
        RAG using In-Memory Numpy Search.
        """
        if not self.model or self.vector_cache is None or len(self.memory_cache) == 0:
            return ""

        query_vec = self._get_embedding(current_thought + " " + current_tool)
        if query_vec is None:
            return ""
        
        # 1. Vector Math (Cosine Similarity)
        # Dot product of Query vs All Vectors
        sims = np.dot(self.vector_cache, query_vec) / (
            np.linalg.norm(self.vector_cache, axis=1) * np.linalg.norm(query_vec)
        )
        
        current_time = time.time()
        scored_memories = []

        # 2. Scoring & Filtering
        for idx, sim in enumerate(sims):
            mem = self.memory_cache[idx]
            
            # Tool Filter (Hard Partition Pruning)
            if mem['tool'] != current_tool and mem['tool'] != 'general':
                continue

            # Time Decay (Recency Bias)
            age_hours = (current_time - mem['timestamp']) / 3600
            time_weight = 1 / (1 + (self.decay_factor * age_hours))
            
            final_score = sim * time_weight
            
            if final_score > 0.65:
                scored_memories.append((final_score, mem))

        # 3. Sort & Format
        scored_memories.sort(key=lambda x: x[0], reverse=True)
        
        lessons = []
        for score, mem in scored_memories[:limit]:
            lessons.append(f"- [Relevance: {int(score*100)}%] WHEN I TRIED: {mem['thought']}\n  FEEDBACK: {mem['human_critique']}")
            
        if not lessons:
            return ""
            
        return "--- RELEVANT PAST LESSONS ---\n" + "\n".join(lessons)

    def close(self):
        # No DB connection to close, files are safe.
        pass