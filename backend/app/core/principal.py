"""The authenticated caller, as seen by services (independent of FastAPI)."""

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: uuid.UUID
    organization_id: uuid.UUID
    role: str
    email: str
    display_name: str
