"""Trusted local administration; never exposed through HTTP."""

import argparse

from pydantic import EmailStr, TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import build_engine
from app.models import User


def promote_organizer(session: Session, email: str) -> bool:
    user = session.scalar(select(User).where(func.lower(User.email) == email.lower()))
    if user is None:
        return False
    user.role = "organizer"
    session.commit()
    return True


def main():
    parser = argparse.ArgumentParser(description="EventFlow local administration")
    parser.add_argument("command", choices=["promote-organizer"])
    parser.add_argument("email")
    args = parser.parse_args()
    email = TypeAdapter(EmailStr).validate_python(args.email)
    engine = build_engine(Settings())
    try:
        with Session(engine) as session:
            if not promote_organizer(session, email):
                parser.exit(1, "User not found; register the account first.\n")
        print("Organizer role assigned.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
