#!/bin/bash
# Reset Database and Reapply Migrations

echo "🗑️  Resetting AI Hunter Database..."

# Drop and recreate the database
echo "Dropping existing database..."
docker exec -it ai-hunter-postgres psql -U hunter -c "DROP DATABASE IF EXISTS ai_hunter;"
docker exec -it ai-hunter-postgres psql -U hunter -c "CREATE DATABASE ai_hunter;"

echo "✅ Database recreated"

# Reset Alembic version tracking
echo "Resetting Alembic version history..."
rm -f alembic/versions/__pycache__/*
echo "✅ Alembic cache cleared"

# Run migrations from scratch
echo "Running migrations..."
poetry run alembic upgrade head

echo "✅ Database reset complete!"
echo ""
echo "📊 New schema with:"
echo "   - 512-dimensional vectors (TensorFlow USE)"
echo "   - Fresh tables with no data"
