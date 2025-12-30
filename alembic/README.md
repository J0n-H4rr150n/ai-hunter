# Alembic Database Migrations

## Setup

Alembic is configured for proper database versioning and migrations.

## Common Commands

### Create a new migration

```bash
# Auto-generate migration from code changes
alembic revision --autogenerate -m "description of changes"

# Create empty migration
alembic revision -m "description of changes"
```

### Apply migrations

```bash
# Upgrade to latest
alembic upgrade head

# Upgrade one version
alembic upgrade +1

# Downgrade one version
alembic downgrade -1
```

### View migration history

```bash
# Show current version
alembic current

# Show migration history
alembic history

# Show pending migrations
alembic history -r current:head
```

## In Docker

Migrations run automatically on container startup via `/app/start.sh`.

To run migrations manually:
```bash
docker-compose exec backend alembic upgrade head
```

## Migration Files

Located in `alembic/versions/`:
- `001_initial_schema.py` - Initial database schema with pgvector

## Configuration

- **alembic.ini** - Main configuration
- **alembic/env.py** - Environment setup
- Uses `DATABASE_URL` environment variable in Docker

## Best Practices

1. **Always review** auto-generated migrations before applying
2. **Test migrations** on development database first
3. **Include both upgrade() and downgrade()** functions
4. **One logical change** per migration
5. **Don't modify** existing migrations after they've been applied to production
