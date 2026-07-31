"""validation layer

Revision ID: 8b21c4f0d7ae
Revises: 41a346f77a37
Create Date: 2026-07-30 20:10:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '8b21c4f0d7ae'
down_revision: Union[str, None] = '41a346f77a37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'validation_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('source_row', sa.Integer(), nullable=False),
        sa.Column('source_file', sa.String(length=255), nullable=True),
        sa.Column('provider', sa.String(length=50), nullable=True),
        sa.Column('provider_place_id', sa.String(length=255), nullable=True),
        sa.Column('business_name', sa.String(length=255), nullable=True),
        sa.Column('categories', sa.Text(), nullable=True),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('city', sa.String(length=120), nullable=True),
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
        sa.Column('google_maps', sa.String(length=3), nullable=True),
        sa.Column('google_maps_link', sa.Text(), nullable=True),
        sa.Column('google_street_view', sa.String(length=3), nullable=True),
        sa.Column('gsv_link', sa.Text(), nullable=True),
        sa.Column('yellow_pages_indonesia', sa.String(length=3), nullable=True),
        sa.Column('yellow_pages_indonesia_link', sa.Text(), nullable=True),
        sa.Column('search_yellow_directory', sa.String(length=3), nullable=True),
        sa.Column('search_yellow_directory_link', sa.Text(), nullable=True),
        sa.Column('indonesia_yp', sa.String(length=3), nullable=True),
        sa.Column('indonesia_yp_link', sa.Text(), nullable=True),
        sa.Column('fresha', sa.String(length=3), nullable=True),
        sa.Column('fresha_link', sa.Text(), nullable=True),
        sa.Column('website_link', sa.Text(), nullable=True),
        sa.Column('services', sa.Text(), nullable=True),
        sa.Column('facebook', sa.Text(), nullable=True),
        sa.Column('instagram', sa.Text(), nullable=True),
        sa.Column('tiktok', sa.Text(), nullable=True),
        sa.Column('whatsapp', sa.Text(), nullable=True),
        sa.Column('identified_contact_number', sa.String(length=120), nullable=True),
        sa.Column('identified_source', sa.Text(), nullable=True),
        sa.Column('validation_notes', sa.Text(), nullable=True),
        sa.Column('validation_status', sa.String(length=30), nullable=False),
        sa.Column('updated_by_email', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'source_row', name='uq_validation_project_row'),
    )
    op.create_index(op.f('ix_validation_records_project_id'), 'validation_records', ['project_id'])
    op.create_index(op.f('ix_validation_records_source_row'), 'validation_records', ['source_row'])
    op.create_index(op.f('ix_validation_records_provider'), 'validation_records', ['provider'])
    op.create_index(op.f('ix_validation_records_business_name'), 'validation_records', ['business_name'])
    op.create_index(op.f('ix_validation_records_evidence_method'), 'validation_records', ['evidence_method'])
    op.create_index(op.f('ix_validation_records_validation_status'), 'validation_records', ['validation_status'])


def downgrade() -> None:
    op.drop_index(op.f('ix_validation_records_validation_status'), table_name='validation_records')
    op.drop_index(op.f('ix_validation_records_evidence_method'), table_name='validation_records')
    op.drop_index(op.f('ix_validation_records_business_name'), table_name='validation_records')
    op.drop_index(op.f('ix_validation_records_provider'), table_name='validation_records')
    op.drop_index(op.f('ix_validation_records_source_row'), table_name='validation_records')
    op.drop_index(op.f('ix_validation_records_project_id'), table_name='validation_records')
    op.drop_table('validation_records')
