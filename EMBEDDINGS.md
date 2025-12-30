# AI Hunter - Embeddings Configuration

## Current Setup: TensorFlow Universal Sentence Encoder

The system uses **TensorFlow Hub** with Google's **Universal Sentence Encoder** from Kaggle for local embeddings.

### Why TensorFlow USE?

✅ **No Hugging Face dependency** - Downloads from Kaggle Models  
✅ **Corporate-friendly** - TensorFlow is widely approved  
✅ **Offline after first download** - Model is cached locally  
✅ **No API calls** - Fully local inference  
✅ **Good quality** - 512-dimensional embeddings  

## Environment Variable

Set in your `.env` file:

```bash
# Disable embeddings (default: true for easier initial setup)
DISABLE_EMBEDDINGS=true

# Enable embeddings (requires TensorFlow, tensorflow-hub, tensorflow-text)
DISABLE_EMBEDDINGS=false
```

## Dependencies

When embeddings are **enabled**, you need:

```bash
pip install tensorflow tensorflow-hub tensorflow-text
```

Or with Poetry:
```bash
poetry install  # Already configured in pyproject.toml
```

## What Gets Disabled

When `DISABLE_EMBEDDINGS=true`:

### ✅ Still Works
- All core functionality
- Finding storage (file-based)
- Feedback storage (JSONL)
- Database operations
- Tool approvals
- Agent actions

### ⏭️ Skipped
- Universal Sentence Encoder model loading (~1GB download first time)
- Vector similarity search
- RAG (Retrieval-Augmented Generation)
- Semantic search
- pgvector embeddings

## Affected Modules

1. **`memory/finding_repository.py`** - Local semantic search using TensorFlow USE
2. **`memory/feedback_memory.py`** - Feedback embeddings via TensorFlow USE
3. **`backend/database.py`** - Tool approval embeddings via TensorFlow USE

All use **512-dimensional vectors** from Universal Sentence Encoder v2.

## Model Source

- **Repository**: [Kaggle Models - Universal Sentence Encoder](https://www.kaggle.com/models/google/universal-sentence-encoder)
- **Handle**: `https://www.kaggle.com/models/google/universal-sentence-encoder/tensorFlow2/universal-sentence-encoder/2`
- **Size**: ~1GB
- **Dimensions**: 512
- **Cache Location**: `~/.tfhub_modules/` (TensorFlow Hub cache)

## First Run

On first run with embeddings enabled:
```
[Memory] Loading Universal Sentence Encoder from Kaggle...
         (First run will download ~1GB model, may take 3-5 minutes)
```

After download, subsequent runs load instantly from cache.

## When to Enable

Enable embeddings (`DISABLE_EMBEDDINGS=false`) when:
- You have TensorFlow dependencies installed
- You want semantic search capabilities
- You need RAG for better context retrieval
- You're okay with ~1GB model download on first run

## Migration from Previous Setup

Previously used:
- ❌ `sentence-transformers` (Hugging Face) - 384 dims
- ❌ Vertex AI `text-embedding-004` - 768 dims

Now using:
- ✅ TensorFlow `universal-sentence-encoder` (Kaggle) - 512 dims
