"""cities

Revision ID: d5f22b8c9a10
Revises: c3d90f1a4e77
Create Date: 2026-07-30 22:20:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'd5f22b8c9a10'
down_revision: Union[str, None] = 'c3d90f1a4e77'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'cities',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('slug', sa.String(length=120), nullable=False),
        sa.Column('region', sa.String(length=120), nullable=True),
        sa.Column('country', sa.String(length=80), nullable=False),
        sa.Column('source_files', sa.JSON(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by_email', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'slug', name='uq_city_project_slug'),
    )
    op.create_index(op.f('ix_cities_project_id'), 'cities', ['project_id'])
    op.create_index(op.f('ix_cities_name'), 'cities', ['name'])
    op.create_index(op.f('ix_cities_slug'), 'cities', ['slug'])

    op.add_column('scrape_jobs', sa.Column('city_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_scrape_jobs_city_id'), 'scrape_jobs', ['city_id'])
    with op.batch_alter_table('scrape_jobs') as batch:
        batch.create_foreign_key('fk_scrape_jobs_city', 'cities', ['city_id'], ['id'])

    connection = op.get_bind()
    # Under the old model an upload created its own copy of every row. Scraping
    # now enriches a city's rows in place, so those copies are folded away first
    # - otherwise they collide with the city rows on the new unique constraint.
    connection.execute(sa.text("DELETE FROM validation_records WHERE job_id IS NOT NULL"))
    connection.execute(sa.text("DELETE FROM scrape_jobs"))

    # job_id described which upload created a row; it now records the last job
    # that processed it.
    with op.batch_alter_table('validation_records') as batch:
        batch.add_column(sa.Column('city_id', sa.Integer(), nullable=True))
        batch.alter_column('job_id', new_column_name='last_job_id')
        batch.drop_constraint('uq_validation_project_row', type_='unique')
        batch.create_unique_constraint('uq_validation_project_row', ['project_id', 'city_id', 'source_row'])
        batch.create_foreign_key('fk_validation_records_city', 'cities', ['city_id'], ['id'])
    op.create_index(op.f('ix_validation_records_city_id'), 'validation_records', ['city_id'])

    # Everything loaded so far came from the bundled Denpasar workbook.
    projects = connection.execute(sa.text(
        "SELECT DISTINCT project_id FROM validation_records WHERE city_id IS NULL"
    )).fetchall()
    for (project_id,) in projects:
        connection.execute(
            sa.text(
                "INSERT INTO cities (project_id, name, slug, region, country, source_files, created_at) "
                "VALUES (:pid, 'Denpasar', 'denpasar', 'Bali', 'Indonesia', '[]', CURRENT_TIMESTAMP)"
            ),
            {"pid": project_id},
        )
        city_id = connection.execute(
            sa.text("SELECT id FROM cities WHERE project_id = :pid AND slug = 'denpasar'"),
            {"pid": project_id},
        ).scalar()
        connection.execute(
            sa.text("UPDATE validation_records SET city_id = :cid WHERE project_id = :pid AND city_id IS NULL"),
            {"cid": city_id, "pid": project_id},
        )


def downgrade() -> None:
    op.drop_index(op.f('ix_validation_records_city_id'), table_name='validation_records')
    with op.batch_alter_table('validation_records') as batch:
        batch.drop_constraint('fk_validation_records_city', type_='foreignkey')
        batch.drop_constraint('uq_validation_project_row', type_='unique')
        batch.alter_column('last_job_id', new_column_name='job_id')
        batch.create_unique_constraint('uq_validation_project_row', ['project_id', 'job_id', 'source_row'])
        batch.drop_column('city_id')
    with op.batch_alter_table('scrape_jobs') as batch:
        batch.drop_constraint('fk_scrape_jobs_city', type_='foreignkey')
    op.drop_index(op.f('ix_scrape_jobs_city_id'), table_name='scrape_jobs')
    op.drop_column('scrape_jobs', 'city_id')
    op.drop_index(op.f('ix_cities_slug'), table_name='cities')
    op.drop_index(op.f('ix_cities_name'), table_name='cities')
    op.drop_index(op.f('ix_cities_project_id'), table_name='cities')
    op.drop_table('cities')
