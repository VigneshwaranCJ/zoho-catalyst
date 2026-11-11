"""Alembic environment.

Migrations run synchronously (psycopg 3 sync mode) as the OWNER role.
The runtime app uses a separate non-owner role so Row-Level Security applies.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.core.config import get_settings
from app.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# LangGraph owns its checkpoint tables in schema "langgraph"; never autogenerate them.
EXCLUDED_SCHEMAS = {"langgraph"}


def include_object(obj, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
    schema = getattr(obj, "schema", None)
    return schema not in EXCLUDED_SCHEMAS


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().owner_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(get_settings().owner_database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
