from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.config import Settings

SCHEMA_REVISION = "0001"
REQUIRED_TABLES = {"users", "events", "rooms", "activities", "registrations"}


def build_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=5,
        connect_args={"connect_timeout": 3, "options": "-c statement_timeout=5000"},
        hide_parameters=True,
    )


def get_session(request: Request) -> Iterator[Session]:
    # Write endpoints must explicitly commit; unfinished transactions roll back.
    with Session(request.app.state.engine) as session:
        yield session
