from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import User
from app.schemas import RegisterRequest, TokenResponse, UserResponse
from app.security import (
    create_access_token,
    decode_subject,
    dummy_hash,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])
oauth2 = OAuth2PasswordBearer(tokenUrl="auth/login")
Database = Annotated[Session, Depends(get_session)]


def unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials or token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    request: Request, session: Database, token: Annotated[str, Depends(oauth2)]
) -> User:
    if len(token) > 8192:
        raise unauthorized()
    try:
        user_id = decode_subject(token, request.app.state.settings)
    except jwt.InvalidTokenError:
        raise unauthorized() from None
    user = session.get(User, user_id)
    if user is None:
        raise unauthorized()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_organizer(user: CurrentUser) -> User:
    # Read the role from the database, never from request input or token claims.
    if user.role != "organizer":
        raise HTTPException(status_code=403, detail="Organizer role required")
    return user


Organizer = Annotated[User, Depends(require_organizer)]


@router.post("/register", status_code=201, response_model=UserResponse)
def register(data: RegisterRequest, session: Database):
    user = User(
        name=data.name,
        email=data.email,
        password_hash=hash_password(data.password.get_secret_value()),
        role="participant",
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if getattr(exc.orig, "sqlstate", None) == "23505":
            raise HTTPException(
                status_code=409, detail="Email already registered"
            ) from None
        raise
    session.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(
    request: Request,
    session: Database,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
):
    # OAuth2 uses a field named 'username'; this API expects the email in it.
    try:
        email = TypeAdapter(EmailStr).validate_python(form.username).lower()
    except ValidationError:
        email = None
    user = (
        session.scalar(select(User).where(func.lower(User.email) == email))
        if email
        else None
    )
    password = form.password if len(form.password) <= 128 else ""
    matches = verify_password(user.password_hash if user else dummy_hash, password)
    if user is None or not matches or len(form.password) > 128:
        raise unauthorized()
    settings = request.app.state.settings
    return TokenResponse(
        access_token=create_access_token(user.id, settings),
        expires_in=settings.access_token_minutes * 60,
    )


@router.get("/me", response_model=UserResponse)
def me(user: CurrentUser):
    return user
