"""Give missions a human name

Missions were identified only by id and target URL, which is fine for one run and
useless once there are twenty against the same host. A short name makes a session
findable later.

Nullable: existing missions keep working and the UI falls back to the target host.

Revision ID: 009_mission_name
Revises: 008_timestamptz
"""
import sqlalchemy as sa
from alembic import op

revision = '009_mission_name'
down_revision = '008_timestamptz'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('missions', sa.Column('name', sa.String(200), nullable=True,
                                        comment='Operator-supplied label for the run'))
    print("✅ Added missions.name")


def downgrade():
    op.drop_column('missions', 'name')
