"""Our stricter OKF profile: `csp-okf-profile/1`.

OKF v0.2 itself only REQUIRES `type` (spec §11). For customer-facing answers we
need more (titles, provenance with page numbers, audience...), so we define a
profile using OKF's own extension mechanism: producers MAY add keys, consumers
MUST preserve unknown keys (spec §4.1). A file that passes the profile is still a
plain, conformant OKF v0.2 concept that any OKF tool can read.

The Pydantic models below ARE the profile's schema; `profile_json_schema()`
exports it as JSON Schema (docs/okf-profile.schema.json).

Spec: https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md
"""

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

OKF_VERSION = "0.2"
PROFILE_ID = "csp-okf-profile/1"

# Actor convention (§7): `<producer>/<version>`, `human:<id>`, `process:<id>`.
ACTOR_RE = re.compile(r"^(human:[\w.@-]+|process:[\w.-]+|[\w.-]+/[\w.-]+)$")
SOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,80}$")


class ConceptType(StrEnum):
    """Our `type` vocabulary. OKF doesn't register types centrally (§4.1)."""

    COMPANY_PROFILE = "Company Profile"
    PRODUCT = "Product"
    SPECIFICATION = "Specification"
    PROCEDURE = "Procedure"
    TROUBLESHOOTING = "Troubleshooting Guide"
    POLICY = "Policy"
    FAQ = "FAQ"
    CONTACT_INFO = "Contact Info"
    SOURCE_DOCUMENT = "Source Document"


# Which top-level folder each type lives in.
TYPE_FOLDERS: dict[ConceptType, str] = {
    ConceptType.COMPANY_PROFILE: "company",
    ConceptType.PRODUCT: "products",
    ConceptType.SPECIFICATION: "products",
    ConceptType.PROCEDURE: "products",
    ConceptType.TROUBLESHOOTING: "products",
    ConceptType.POLICY: "policies",
    ConceptType.FAQ: "support",
    ConceptType.CONTACT_INFO: "support",
    ConceptType.SOURCE_DOCUMENT: "sources",
}


def _iso_with_offset(value: Any) -> str:
    """OKF timestamps are ISO 8601 datetimes WITH an explicit offset (spec, Aug 2026)."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("datetime must include a UTC offset")
        return value.isoformat()
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("datetime must include a UTC offset")
        return value
    raise ValueError("expected an ISO 8601 datetime")


IsoDateTime = Annotated[str, Field(description="ISO 8601 datetime with offset")]


class Locator(BaseModel):
    """Profile extension: where in the source a fact comes from."""

    model_config = ConfigDict(extra="allow")
    page: int | None = Field(default=None, ge=1)
    section: str | None = Field(default=None, max_length=300)


class SourceEntry(BaseModel):
    model_config = ConfigDict(extra="allow")  # unknown keys must be preserved (§4.1)

    id: str = Field(pattern=SOURCE_ID_RE.pattern)  # profile: REQUIRED (OKF: optional)
    resource: str = Field(min_length=1)  # OKF: REQUIRED within an entry (§5.1)
    title: str | None = None
    author: str | None = None
    last_modified: IsoDateTime | None = None
    # profile extensions
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    locators: list[Locator] = Field(default_factory=list)

    @field_validator("last_modified", mode="before")
    @classmethod
    def _ts(cls, v: Any) -> Any:
        return None if v is None else _iso_with_offset(v)


class ActorEvent(BaseModel):
    model_config = ConfigDict(extra="allow")
    by: str = Field(pattern=ACTOR_RE.pattern)
    at: IsoDateTime | None = None

    @field_validator("at", mode="before")
    @classmethod
    def _ts(cls, v: Any) -> Any:
        return None if v is None else _iso_with_offset(v)


class ConceptFrontmatter(BaseModel):
    """Frontmatter of a customer-support concept document under our profile."""

    model_config = ConfigDict(extra="allow")

    # OKF core (§4.1). type is the only key OKF itself requires.
    type: str = Field(min_length=1)
    title: str = Field(min_length=3, max_length=200)  # profile: required
    description: str = Field(min_length=10, max_length=400)  # profile: required
    resource: str | None = None
    tags: list[str] = Field(default_factory=list)
    # Provenance / trust / lifecycle (§5)
    sources: list[SourceEntry] = Field(min_length=1)  # profile: at least one
    generated: ActorEvent  # profile: required
    verified: list[ActorEvent] = Field(default_factory=list)
    status: Literal["draft", "stable", "deprecated"] = "stable"
    stale_after: IsoDateTime | None = None
    # Profile extensions
    audience: Literal["customer", "internal"]
    products: list[str] = Field(default_factory=list)

    @field_validator("verified", mode="before")
    @classmethod
    def _bare_mapping_is_one_element_list(cls, v: Any) -> Any:
        return [v] if isinstance(v, dict) else v  # spec §5.2: MUST accept a bare mapping

    @field_validator("stale_after", mode="before")
    @classmethod
    def _ts(cls, v: Any) -> Any:
        return None if v is None else _iso_with_offset(v)


def trust_tier(
    verified: list[ActorEvent],
) -> Literal["unverified", "machine-confirmed", "human-reviewed"]:
    """Spec §5.3: derived from `verified`, never stored."""
    if not verified:
        return "unverified"
    if any(e.by.startswith("human:") for e in verified):
        return "human-reviewed"
    return "machine-confirmed"


def profile_json_schema() -> dict[str, Any]:
    schema = ConceptFrontmatter.model_json_schema()
    schema["$id"] = f"https://csp.example/schemas/{PROFILE_ID}.json"
    schema["title"] = f"{PROFILE_ID} concept frontmatter (OKF v{OKF_VERSION} compatible)"
    return schema
