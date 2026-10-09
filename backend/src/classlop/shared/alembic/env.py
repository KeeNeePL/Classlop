from importlib import import_module
from importlib.util import find_spec

from alembic import context
from sqlalchemy import create_engine, text

from classlop.shared.db import SCHEMAS, Base
from classlop.shared.settings import get_settings

# Any fixed number: concurrent `web` tasks starting together then migrate one at a time.
MIGRATE_LOCK = 6301

for area in SCHEMAS:
    if find_spec(f"classlop.{area}.models"):
        import_module(f"classlop.{area}.models")


def include_name(name, type_, parent_names) -> bool:
    return type_ != "schema" or name in SCHEMAS


engine = create_engine(get_settings().database_url)
with engine.connect() as conn:
    conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": MIGRATE_LOCK})
    for schema in SCHEMAS:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
    conn.commit()
    context.configure(
        connection=conn,
        target_metadata=Base.metadata,
        version_table_schema="shared",
        include_schemas=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
