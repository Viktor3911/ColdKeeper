"""Browser sessions and sign-in throttling rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SessionPolicy:
    """Idle and absolute session lifetime."""

    idle_timeout: timedelta = timedelta(days=7)
    absolute_timeout: timedelta = timedelta(days=30)
    # Avoid a database write on every request: extend the session at most this often.
    touch_interval: timedelta = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class UserSession:
    """A server-side session; the cookie holds a random id, the database only its hash."""

    id_hash: str
    user_id: UUID
    csrf_token: str
    created_at: datetime
    last_seen_at: datetime

    def is_expired(self, now: datetime, policy: SessionPolicy) -> bool:
        """Expired by inactivity or by total age."""
        return now - self.last_seen_at > policy.idle_timeout or now - self.created_at > policy.absolute_timeout

    def needs_touch(self, now: datetime, policy: SessionPolicy) -> bool:
        """Whether ``last_seen_at`` should be refreshed."""
        return now - self.last_seen_at > policy.touch_interval


@dataclass(frozen=True, slots=True)
class ThrottlePolicy:
    """Failed sign-ins per login and client address before a pause."""

    max_failures: int = 5
    lockout: timedelta = timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class LoginAttempts:
    """Failed attempts counter of a (login, address) pair."""

    failures: int
    locked_until: datetime | None

    def locked(self, now: datetime) -> timedelta | None:
        """Remaining lockout, if any."""
        if self.locked_until is not None and self.locked_until > now:
            return self.locked_until - now
        return None
