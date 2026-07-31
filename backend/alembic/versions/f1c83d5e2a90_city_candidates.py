"""city candidates

Separates benchmark analytics rows from the validation queue. Candidates from a
benchmark export now live in city_candidates and feed the executive views only;
validation_records is loaded from a city's validation workbook and drives the
validation layer and scraping.

Revision ID: f1c83d5e2a90
Revises: e7a41c02b8d3
Create Date: 2026-07-31 15:05:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f1c83d5e2a90'
down_revision: Union[str, None] = 'e7a41c02b8d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'city_candidates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('city_id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=True),
        sa.Column('provider_place_id', sa.String(length=255), nullable=True),
        sa.Column('business_name', sa.String(length=255), nullable=True),
        sa.Column('categories', sa.Text(), nullable=True),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('city_name', sa.String(length=120), nullable=True),
        sa.Column('province', sa.String(length=120), nullable=True),
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.Column('phone', sa.String(length=120), nullable=True),
        sa.Column('website', sa.Text(), nullable=True),
        sa.Column('business_status', sa.String(length=120), nullable=True),
        sa.Column('evidence_method', sa.String(length=80), nullable=True),
        sa.Column('evidence_strength', sa.Text(), nullable=True),
        sa.Column('probe_query', sa.Text(), nullable=True),
        sa.Column('result_count', sa.Integer(), nullable=True),
        sa.Column('best_score', sa.Float(), nullable=True),
        sa.Column('evidence_timestamp', sa.String(length=80), nullable=True),
        sa.Column('evidence_reason', sa.Text(), nullable=True),
        sa.Column('found_by_probe', sa.String(length=20), nullable=True),
        sa.Column('role', sa.String(length=40), nullable=True),
        sa.Column('customer_tier', sa.String(length=40), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['city_id'], ['cities.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('city_id', 'provider', 'provider_place_id', name='uq_city_candidate_place'),
    )
    op.create_index(op.f('ix_city_candidates_city_id'), 'city_candidates', ['city_id'])
    op.create_index(op.f('ix_city_candidates_provider'), 'city_candidates', ['provider'])
    op.create_index(op.f('ix_city_candidates_business_name'), 'city_candidates', ['business_name'])
    op.create_index(op.f('ix_city_candidates_evidence_method'), 'city_candidates', ['evidence_method'])
    op.create_index(op.f('ix_city_candidates_role'), 'city_candidates', ['role'])
    op.create_index(op.f('ix_city_candidates_customer_tier'), 'city_candidates', ['customer_tier'])

    # Move the benchmark rows out of the validation queue. A benchmarked city is
    # re-imported into city_candidates and gets its own validation workbook.
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "DELETE FROM validation_records WHERE city_id IN "
            "(SELECT id FROM cities WHERE headline IS NOT NULL)"
        )
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_city_candidates_customer_tier'), table_name='city_candidates')
    op.drop_index(op.f('ix_city_candidates_role'), table_name='city_candidates')
    op.drop_index(op.f('ix_city_candidates_evidence_method'), table_name='city_candidates')
    op.drop_index(op.f('ix_city_candidates_business_name'), table_name='city_candidates')
    op.drop_index(op.f('ix_city_candidates_provider'), table_name='city_candidates')
    op.drop_index(op.f('ix_city_candidates_city_id'), table_name='city_candidates')
    op.drop_table('city_candidates')
