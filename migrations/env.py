from alembic import context
from sqlalchemy import create_engine, pool

from app.config import Settings


def run_migrations_online():
    # Pass the URL directly, never through ConfigParser (passwords may contain %).
    engine = create_engine(
        Settings().database_url.get_secret_value(),
        poolclass=pool.NullPool,
        connect_args={"connect_timeout": 3},
        hide_parameters=True,
    )
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=None)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Use online migrations: alembic upgrade head")
else:
    run_migrations_online()
