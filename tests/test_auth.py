import os
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Organizer
from app.config import Settings
from app.database import build_engine, get_session
from app.main import create_app
from app.manage import promote_organizer
from app.models import User
from app.security import AUDIENCE, ISSUER, hash_password, verify_password

SECRET = "test-only-signing-secret-at-least-32-bytes"
PASSWORD = "Test-password-123!"
EMAIL = "participant@example.com"


@pytest.fixture
def auth():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requires migrated test PostgreSQL")
    settings = Settings(database_url=url, jwt_secret=SECRET, _env_file=None)
    engine = build_engine(settings)
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(
            bind=connection, join_transaction_mode="create_savepoint"
        ) as session:
            app = create_app(settings)

            def override_session():
                yield session

            app.dependency_overrides[get_session] = override_session

            @app.get("/test-organizer")
            def organizer_only(user: Organizer):
                return {"id": user.id}

            with TestClient(app) as client:
                yield client, session
        transaction.rollback()
    engine.dispose()


def register(client, **changes):
    body = {"name": " Participant ", "email": EMAIL, "password": PASSWORD}
    body.update(changes)
    return client.post("/auth/register", json=body)


def login(client, username=EMAIL, password=PASSWORD):
    return client.post("/auth/login", data={"username": username, "password": password})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def claims(user_id):
    now = datetime.now(UTC)
    return {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=10),
        "iss": ISSUER,
        "aud": AUDIENCE,
    }


def test_password_hash_is_salted_argon2id():
    first, second = hash_password(PASSWORD), hash_password(PASSWORD)
    assert first.startswith("$argon2id$")
    assert first != second
    assert verify_password(first, PASSWORD)
    assert not verify_password(first, "wrong")
    assert not verify_password("invalid-hash", PASSWORD)


def test_register_login_me(auth):
    client, session = auth
    response = register(client, email="Participant@EXAMPLE.COM")
    assert response.status_code == 201
    data = response.json()
    assert data["role"] == "participant"
    assert data["name"] == "Participant"
    assert data["email"] == EMAIL
    assert "password" not in data and "password_hash" not in data
    user = session.get(User, data["id"])
    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash
    response = login(client, username="PARTICIPANT@example.com")
    assert response.status_code == 200
    token = response.json()
    assert token["token_type"] == "bearer"
    assert token["expires_in"] == 1800
    response = client.get("/auth/me", headers=bearer(token["access_token"]))
    assert response.status_code == 200
    assert response.json() == data


def test_duplicate_email(auth):
    client, _ = auth
    assert register(client).status_code == 201
    assert register(client, email=EMAIL.upper()).status_code == 409
    assert login(client).status_code == 200  # Session recovered after rollback.


@pytest.mark.parametrize(
    "changes",
    [
        {"role": "organizer"},
        {"id": 1},
        {"name": "   "},
        {"email": "invalid-email"},
        {"password": "short"},
        {"password": "x" * 129},
    ],
)
def test_invalid_registration_and_role_injection(auth, changes):
    client, session = auth
    response = register(client, **changes)
    assert response.status_code == 422
    assert PASSWORD not in response.text
    assert all("input" not in error for error in response.json()["detail"])
    assert session.scalar(select(User).where(User.email == EMAIL)) is None


@pytest.mark.parametrize(
    "username,password",
    [
        (EMAIL, "wrong"),
        ("unknown@example.com", PASSWORD),
        ("not-an-email", PASSWORD),
        (EMAIL, "x" * 129),
    ],
)
def test_invalid_login_has_same_error(auth, username, password):
    client, _ = auth
    register(client)
    response = login(client, username=username, password=password)
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials or token"}
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "headers", [{}, bearer("garbage"), {"Authorization": "Basic abc"}]
)
def test_me_requires_valid_bearer(auth, headers):
    client, _ = auth
    assert client.get("/auth/me", headers=headers).status_code == 401


@pytest.mark.parametrize(
    "kind",
    [
        "expired",
        "wrong-key",
        "wrong-audience",
        "wrong-issuer",
        "missing-exp",
        "future-iat",
        "oversized-id",
        "unknown-user",
        "wrong-algorithm",
    ],
)
def test_reject_invalid_jwt(auth, kind):
    client, _ = auth
    user_id = register(client).json()["id"]
    payload = claims(user_id)
    key, algorithm = SECRET, "HS256"
    if kind == "expired":
        payload["exp"] = datetime.now(UTC) - timedelta(seconds=5)
    elif kind == "wrong-key":
        key = "another-test-key-at-least-32-bytes-long"
    elif kind == "wrong-audience":
        payload["aud"] = "other"
    elif kind == "wrong-issuer":
        payload["iss"] = "other"
    elif kind == "missing-exp":
        del payload["exp"]
    elif kind == "future-iat":
        payload["iat"] = datetime.now(UTC) + timedelta(hours=1)
    elif kind == "oversized-id":
        payload["sub"] = "9" * 40
    elif kind == "unknown-user":
        payload["sub"] = "9223372036854775807"
    elif kind == "wrong-algorithm":
        key, algorithm = SECRET * 2, "HS384"
    token = jwt.encode(payload, key, algorithm=algorithm)
    assert client.get("/auth/me", headers=bearer(token)).status_code == 401


def test_organizer_dependency_reads_current_database_role(auth):
    client, session = auth
    user_id = register(client).json()["id"]
    payload = claims(user_id)
    payload["role"] = "organizer"  # Even a signed role claim is ignored.
    token = jwt.encode(payload, SECRET, algorithm="HS256")
    headers = bearer(token)
    assert client.get("/test-organizer").status_code == 401
    assert client.get("/test-organizer", headers=headers).status_code == 403
    user = session.get(User, user_id)
    assert not promote_organizer(session, "missing@example.com")
    assert promote_organizer(session, EMAIL.upper())
    assert client.get("/test-organizer", headers=headers).status_code == 200
    user.role = "participant"
    session.commit()
    assert client.get("/test-organizer", headers=headers).status_code == 403
    session.delete(user)
    session.commit()
    assert client.get("/auth/me", headers=headers).status_code == 401


def test_short_signing_secret_rejected():
    with pytest.raises(ValueError, match="at least 32 bytes"):
        Settings(
            database_url="postgresql+psycopg://localhost/test",
            jwt_secret="short",
            _env_file=None,
        )
