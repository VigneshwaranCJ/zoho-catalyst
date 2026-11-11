"""Seed local development data: the TechNova Electronics demo organization.

    uv run python -m scripts.seed

Idempotent: running it twice doesn't create duplicates. Runs as the OWNER DB
role (bypasses RLS) because creating organizations is a platform-level action.
Refuses to run in production.
"""

import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.organization import Organization
from app.models.user import User

DEMO_ORG_SLUG = "technova"


def seed() -> None:
    settings = get_settings()
    if settings.is_production:
        sys.exit("Refusing to seed demo data in production.")
    password = settings.seed_admin_password.get_secret_value()
    if len(password) < 12:
        sys.exit("Set SEED_ADMIN_PASSWORD (min 12 chars) in .env first.")

    engine = create_engine(settings.owner_database_url)
    with Session(engine) as session, session.begin():
        org = session.scalar(select(Organization).where(Organization.slug == DEMO_ORG_SLUG))
        if org is None:
            org = Organization(
                slug=DEMO_ORG_SLUG,
                name="TechNova Electronics",
                settings={"sensitive_topics": ["legal", "safety", "billing_dispute"]},
            )
            session.add(org)
            session.flush()
            print(f"created organization {org.slug} ({org.id})")

        admin = session.scalar(
            select(User).where(
                User.organization_id == org.id, User.email == settings.seed_admin_email
            )
        )
        if admin is None:
            session.add(
                User(
                    organization_id=org.id,
                    email=settings.seed_admin_email,
                    display_name="TechNova Admin",
                    role="org_admin",
                    password_hash=hash_password(password),
                )
            )
            print(f"created admin user {settings.seed_admin_email}")
        else:
            print("admin user already exists")
    engine.dispose()


if __name__ == "__main__":
    seed()
