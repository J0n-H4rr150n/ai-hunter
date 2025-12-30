# Database Reset Instructions

## Quick Reset (Recommended)

```bash
# 1. Make sure Docker is running
docker compose up -d postgres

# 2. Wait for postgres to be ready (5-10 seconds)
sleep 10

# 3. Drop and recreate database
docker exec ai-hunter-postgres psql -U hunter -c "DROP DATABASE IF EXISTS ai_hunter;"
docker exec ai-hunter-postgres psql -U hunter -c "CREATE DATABASE ai_hunter;"

# 4. Run migrations
poetry run alembic upgrade head

echo "✅ Database reset complete with 512-dim vectors!"
```

## Alternative: Using the Script

```bash
# On Linux/Mac:
chmod +x scripts/reset_database.sh
./scripts/reset_database.sh

# On Windows (Git Bash):
bash scripts/reset_database.sh
```

## What Changed

### Before:
- sentence-transformers (Hugging Face) - 384 dims
- Vertex AI text-embedding-004 - 768 dims

### After:
- ✅ TensorFlow Universal Sentence Encoder (Kaggle) - **512 dims**
- ✅ No Hugging Face dependency
- ✅ No API calls required
- ✅ Fully offline after first model download (~1GB)

## Verify Schema

After reset, check the vector dimensions:

```bash
docker exec ai-hunter-postgres psql -U hunter -d ai_hunter -c "\d tool_approvals"
docker exec ai-hunter-postgres psql -U hunter -d ai_hunter -c "\d findings"
```

Should show `embedding | vector(512)`
