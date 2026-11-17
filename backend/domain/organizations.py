"""Organizations, users and the actor performing an action."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from backend.domain.errors import PermissionDeniedError


class Role(enum.StrEnum):
    """Minimal MVP roles."""

    OWNER = "owner"  # settings, sensors, recipients + everything an observer can do
    OBSERVER = "observer"  # read and export only


@dataclass(frozen=True, slots=True)
class Organization:
    """A client company; all data belongs to exactly one organization."""

    id: UUID
    name: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class User:
    """A person who signs in to the web interface."""

    id: UUID
    organization_id: UUID
    login: str
    password_hash: str
    role: Role
    is_active: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Actor:
    """Who performs a use case; every read and write is scoped by ``organization_id``."""

    user_id: UUID
    organization_id: UUID
    role: Role

    def require_owner(self) -> None:
        """Raise unless the actor may change settings."""
        if self.role is not Role.OWNER:
            raise PermissionDeniedError("Действие доступно только владельцу организации")
