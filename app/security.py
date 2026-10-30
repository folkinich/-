import secrets
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.config import Settings

password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
# Verify a real hash even for unknown emails, reducing account enumeration by timing.
dummy_hash = password_hasher.hash(secrets.token_urlsafe(32))
ISSUER = "eventflow"
AUDIENCE = "eventflow-api"


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(encoded: str, password: str) -> bool:
    try:
        return password_hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: int, settings: Settings) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "iat": now,
            "exp": now + timedelta(minutes=settings.access_token_minutes),
            "iss": ISSUER,
            "aud": AUDIENCE,
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )


def decode_subject(token: str, settings: Settings) -> int:
    claims = jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=["HS256"],
        issuer=ISSUER,
        audience=AUDIENCE,
        options={"require": ["sub", "iat", "exp", "iss", "aud"]},
    )
    subject = claims["sub"]
    if not isinstance(subject, str) or not subject.isascii() or not subject.isdecimal():
        raise jwt.InvalidTokenError("Invalid subject")
    # Reject oversized IDs before querying the bigint column.
    if len(subject) > 19 or not 0 < int(subject) <= 9223372036854775807:
        raise jwt.InvalidTokenError("Invalid subject")
    return int(subject)
