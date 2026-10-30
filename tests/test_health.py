import os
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from app.config import Settings
from app.database import REQUIRED_TABLES, SCHEMA_REVISION
from app.main import create_app


@pytest.fixture
def client():
    settings = Settings(
        database_url="postgresql+psycopg://test:private@localhost/eventflow",
        jwt_secret="test-only-signing-secret-32-bytes-long",
        _env_file=None,
    )
    with TestClient(create_app(settings)) as client:
        yield client


def test_live_does_not_require_database(client):
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/docs").status_code == 200


def test_ready_does_not_expose_database_errors(client, monkeypatch):
    engine = MagicMock()
    engine.connect.side_effect = OperationalError(
        "secret-url", {}, Exception("private")
    )
    monkeypatch.setattr(client.app.state, "engine", engine)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


@pytest.mark.parametrize(
    "revisions,tables,status",
    [
        ([SCHEMA_REVISION], REQUIRED_TABLES, 200),
        (["outdated"], REQUIRED_TABLES, 503),
        ([SCHEMA_REVISION], REQUIRED_TABLES - {"registrations"}, 503),
        ([], REQUIRED_TABLES, 503),
    ],
)
def test_ready_requires_current_schema(client, monkeypatch, revisions, tables, status):
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.side_effect = [
        MagicMock(scalars=lambda: revisions),
        MagicMock(scalars=lambda: tables),
    ]
    monkeypatch.setattr(client.app.state, "engine", engine)
    assert client.get("/health/ready").status_code == status


def test_database_settings_reject_other_drivers():
    with pytest.raises(ValidationError):
        Settings(database_url="sqlite:///db.sqlite", _env_file=None)


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="Requires migrated test PostgreSQL"
)
def test_ready_with_real_postgresql():
    settings = Settings(
        database_url=os.environ["TEST_DATABASE_URL"],
        jwt_secret="test-only-signing-secret-32-bytes-long",
        _env_file=None,
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ready"}
