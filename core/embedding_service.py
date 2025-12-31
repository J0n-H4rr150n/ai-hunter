"""
Local Embedding Service for Attack Pattern RAG

Uses TensorFlow Hub's Universal Sentence Encoder (offline, no external API calls).
Generates 512-dimensional embeddings compatible with pgvector.
"""

import tensorflow as tf
import tensorflow_hub as hub
import numpy as np
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)


class LocalEmbeddingService:
    """
    Local embedding generation using TensorFlow Hub Universal Sentence Encoder.
    
    Model: Universal Sentence Encoder v4
    - Dimensions: 512
    - Offline: Downloads once, caches locally
    - Quality: Excellent for semantic search
    """
    
    def __init__(self, model_url: str = "https://tfhub.dev/google/universal-sentence-encoder/4"):
        """
        Initialize embedding service with TensorFlow Hub model.
        
        Args:
            model_url: TensorFlow Hub model URL (downloads once, caches locally)
        """
        logger.info(f"[Embeddings] Loading TensorFlow Hub model...")
        try:
            self.model = hub.load(model_url)
            self.dimension = 512  # Universal Sentence Encoder dimension
            logger.info(f"[Embeddings] ✅ Model loaded. Dimension: {self.dimension}")
        except Exception as e:
            logger.error(f"[Embeddings] ❌ Failed to load model: {e}")
            raise
    
    def embed_text(self, text: str) -> np.ndarray:
        """
        Generate embedding for a single text string.
        
        Args:
            text: Input text to embed
            
        Returns:
            NumPy array of shape (512,)
        """
        if not text or not text.strip():
            logger.warning("[Embeddings] Empty text provided, returning zero vector")
            return np.zeros(self.dimension)
        
        try:
            # TensorFlow Hub expects list input
            embeddings = self.model([text])
            # Convert to numpy and get first (only) result
            embedding = embeddings.numpy()[0]
            # Normalize for cosine similarity
            embedding = embedding / np.linalg.norm(embedding)
            return embedding
        except Exception as e:
            logger.error(f"[Embeddings] Error embedding text: {e}")
            return np.zeros(self.dimension)
    
    def embed_texts(self, texts: List[str]) -> np.ndarray:
        """
        Generate embeddings for multiple texts (batch processing).
        
        Args:
            texts: List of input texts
            
        Returns:
            NumPy array of shape (len(texts), 512)
        """
        if not texts:
            return np.array([])
        
        try:
            embeddings = self.model(texts)
            embeddings_np = embeddings.numpy()
            # Normalize for cosine similarity
            norms = np.linalg.norm(embeddings_np, axis=1, keepdims=True)
            embeddings_normalized = embeddings_np / norms
            return embeddings_normalized
        except Exception as e:
            logger.error(f"[Embeddings] Error embedding texts: {e}")
            return np.zeros((len(texts), self.dimension))
    
    def embed_pattern(self, pattern: Dict[str, Any]) -> np.ndarray:
        """
        Generate embedding for an attack pattern YAML structure.
        
        Combines multiple fields to create a rich semantic representation:
        - Pattern name
        - Description
        - Indicators
        - Attack sequence steps
        - Tags
        
        Args:
            pattern: Parsed YAML pattern dictionary
            
        Returns:
            NumPy array of shape (512,)
        """
        try:
            # Extract all text components
            text_parts = []
            
            # Metadata
            if 'metadata' in pattern:
                metadata = pattern['metadata']
                if 'name' in metadata:
                    text_parts.append(f"Pattern: {metadata['name']}")
                if 'tags' in metadata:
                    text_parts.append(f"Tags: {' '.join(metadata['tags'])}")
                if 'difficulty' in metadata:
                    text_parts.append(f"Difficulty: {metadata['difficulty']}")
            
            # Pattern content
            if 'pattern' in pattern:
                pattern_data = pattern['pattern']
                
                # Description
                if 'description' in pattern_data:
                    text_parts.append(pattern_data['description'])
                
                # Indicators
                if 'indicators' in pattern_data:
                    indicators = pattern_data['indicators']
                    text_parts.append("Indicators: " + " ".join(indicators))
                
                # Attack sequence
                if 'attack_sequence' in pattern_data:
                    steps = pattern_data['attack_sequence']
                    step_texts = [
                        f"Step {step['step']}: {step['action']}"
                        for step in steps
                    ]
                    text_parts.append(" ".join(step_texts))
            
            # Combine all text
            combined_text = "\n".join(text_parts)
            
            logger.debug(f"[Embeddings] Embedding pattern text ({len(combined_text)} chars)")
            
            return self.embed_text(combined_text)
            
        except Exception as e:
            logger.error(f"[Embeddings] Error embedding pattern: {e}")
            return np.zeros(self.dimension)
    
    def compute_similarity(self, embedding1: np.ndarray, embedding2: np.ndarray) -> float:
        """
        Compute cosine similarity between two embeddings.
        
        Args:
            embedding1: First embedding vector
            embedding2: Second embedding vector
            
        Returns:
            Cosine similarity score (0-1, higher is more similar)
        """
        try:
            # Cosine similarity for normalized vectors is just dot product
            similarity = np.dot(embedding1, embedding2)
            return float(similarity)
        except Exception as e:
            logger.error(f"[Embeddings] Error computing similarity: {e}")
            return 0.0


# Global instance (lazy-loaded)
_embedding_service: LocalEmbeddingService | None = None


def get_embedding_service() -> LocalEmbeddingService:
    """Get or create the global embedding service instance."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = LocalEmbeddingService()
    return _embedding_service

