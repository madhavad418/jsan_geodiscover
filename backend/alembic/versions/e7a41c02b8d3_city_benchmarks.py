"""city benchmarks

Revision ID: e7a41c02b8d3
Revises: d5f22b8c9a10
Create Date: 2026-07-31 14:10:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'e7a41c02b8d3'
down_revision: Union[str, None] = 'd5f22b8c9a10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'city_matches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('city_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=30), nullable=False),
        sa.Column('match_score', sa.Float(), nullable=True),
        sa.Column('distance_m', sa.Float(), nullable=True),
        sa.Column('method', sa.String(length=60), nullable=True),
        sa.Column('signal_breakdown', sa.Text(), nullable=True),
        sa.Column('grab_place_id', sa.String(length=255), nullable=True),
        sa.Column('grab_name', sa.String(length=255), nullable=True),
        sa.Column('grab_address', sa.Text(), nullable=True),
        sa.Column('grab_latitude', sa.Float(), nullable=True),
        sa.Column('grab_longitude', sa.Float(), nullable=True),
        sa.Column('google_place_id', sa.String(length=255), nullable=True),
        sa.Column('google_name', sa.String(length=255), nullable=True),
        sa.Column('google_address', sa.Text(), nullable=True),
        sa.Column('google_latitude', sa.Float(), nullable=True),
        sa.Column('google_longitude', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['city_id'], ['cities.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_city_matches_city_id'), 'city_matches', ['city_id'])
    op.create_index(op.f('ix_city_matches_kind'), 'city_matches', ['kind'])

    with op.batch_alter_table('cities') as batch:
        batch.add_column(sa.Column('headline', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('coverage', sa.JSON(), nullable=True))

    with op.batch_alter_table('validation_records') as batch:
        batch.add_column(sa.Column('role', sa.String(length=40), nullable=True))
        batch.add_column(sa.Column('customer_tier', sa.String(length=40), nullable=True))
    op.create_index(op.f('ix_validation_records_role'), 'validation_records', ['role'])
    op.create_index(op.f('ix_validation_records_customer_tier'), 'validation_records', ['customer_tier'])


def downgrade() -> None:
    op.drop_index(op.f('ix_validation_records_customer_tier'), table_name='validation_records')
    op.drop_index(op.f('ix_validation_records_role'), table_name='validation_records')
    with op.batch_alter_table('validation_records') as batch:
        batch.drop_column('customer_tier')
        batch.drop_column('role')
    with op.batch_alter_table('cities') as batch:
        batch.drop_column('coverage')
        batch.drop_column('headline')
    op.drop_index(op.f('ix_city_matches_kind'), table_name='city_matches')
    op.drop_index(op.f('ix_city_matches_city_id'), table_name='city_matches')
    op.drop_table('city_matches')
