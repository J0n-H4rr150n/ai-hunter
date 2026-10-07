"""Store all timestamps as TIMESTAMPTZ

Every timestamp column was "timestamp without time zone". The application writes
timezone-aware UTC, so the offset was being discarded on the way in and the value
came back out with no indication of what zone it was in. Anything reading the
database directly had to guess, and the UI could not convert reliably.

Existing rows were written as UTC, so they are reinterpreted as UTC rather than as
the server's local zone.

Revision ID: 008_timestamptz
Revises: 007_add_attack_patterns
"""
from alembic import op
from sqlalchemy import text as sa_text

revision = '008_timestamptz'
down_revision = '007_add_attack_patterns'
branch_labels = None
depends_on = None

# table -> columns
COLUMNS = {
    'activity_logs': ['timestamp'],
    'agent_actions': ['created_at'],
    'agent_memory': ['created_at'],
    'agent_thoughts': ['timestamp'],
    'artifacts': ['created_at'],
    'attack_patterns': ['created_at', 'updated_at'],
    'findings': ['created_at'],
    'human_interactions': ['created_at'],
    'iterations': ['created_at', 'started_at', 'completed_at'],
    'llm_traces': ['timestamp_start', 'timestamp_end'],
    'missions': ['created_at', 'updated_at', 'completed_at'],
    'network_traffic': ['timestamp'],
    'pattern_indicators': ['created_at'],
    'pattern_steps': ['created_at'],
    'pattern_usage': ['created_at'],
    'settings': ['updated_at'],
    'state_snapshots': ['created_at'],
    'tool_approvals': ['created_at'],
    'tool_executions': ['started_at', 'completed_at'],
}


def _exists(conn, table, column):
    return conn.execute(sa_text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=:t AND column_name=:c"
    ), {"t": table, "c": column}).first() is not None


def upgrade():
    conn = op.get_bind()
    for table, columns in COLUMNS.items():
        for column in columns:
            if not _exists(conn, table, column):
                continue
            op.execute(
                f'ALTER TABLE {table} ALTER COLUMN "{column}" '
                f'TYPE TIMESTAMPTZ USING "{column}" AT TIME ZONE \'UTC\''
            )
    print("✅ Converted timestamp columns to TIMESTAMPTZ (existing values read as UTC)")


def downgrade():
    conn = op.get_bind()
    for table, columns in COLUMNS.items():
        for column in columns:
            if not _exists(conn, table, column):
                continue
            op.execute(
                f'ALTER TABLE {table} ALTER COLUMN "{column}" '
                f'TYPE TIMESTAMP USING "{column}" AT TIME ZONE \'UTC\''
            )
