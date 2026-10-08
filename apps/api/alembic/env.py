from alembic import context
from sqlalchemy import create_engine, pool

from apps.api.app.core.config import get_settings
from apps.api.app.domain import models  # noqa: F401
from apps.api.app.domain.base import Base

config = context.config
target_metadata = Base.metadata
url = str(get_settings().database_url)

if context.is_offline_mode():
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
