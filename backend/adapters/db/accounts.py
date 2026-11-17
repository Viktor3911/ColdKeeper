"""Organizations, users, sessions and sign-in counters."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.adapters.db.models import LoginAttemptRow, OrganizationRow, SessionRow, UserRow
from backend.domain.auth import LoginAttempts, UserSession
from backend.domain.organizations import Organization, Role, User


def _organization(row: OrganizationRow) -> Organization:
    return Organization(id=row.id, name=row.name, created_at=row.created_at)


def _user(row: UserRow) -> User:
    return User(
        id=row.id,
        organization_id=row.organization_id,
        login=row.login,
        password_hash=row.password_hash,
        role=Role(row.role),
        is_active=row.is_active,
        created_at=row.created_at,
    )


class SqlOrganizationRepository:
    """:class:`backend.application.ports.OrganizationRepository` on PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, organization: Organization) -> None:
        """Insert."""
        self._session.add(
            OrganizationRow(id=organization.id, name=organization.name, created_at=organization.created_at)
        )
        await self._session.flush()

    async def get(self, organization_id: UUID) -> Organization | None:
        """By id."""
        row = await self._session.get(OrganizationRow, organization_id)
        return None if row is None else _organization(row)

    async def get_by_name(self, name: str) -> Organization | None:
        """By exact name."""
        row = await self._session.scalar(select(OrganizationRow).where(OrganizationRow.name == name))
        return None if row is None else _organization(row)


class SqlUserRepository:
    """:class:`backend.application.ports.UserRepository` on PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: User) -> None:
        """Insert."""
        self._session.add(
            UserRow(
                id=user.id,
                organization_id=user.organization_id,
                login=user.login,
                password_hash=user.password_hash,
                role=user.role.value,
                is_active=user.is_active,
                created_at=user.created_at,
            ),
        )
        await self._session.flush()

    async def get(self, user_id: UUID) -> User | None:
        """By id."""
        row = await self._session.get(UserRow, user_id)
        return None if row is None else _user(row)

    async def get_by_login(self, login: str) -> User | None:
        """By normalized login."""
        row = await self._session.scalar(select(UserRow).where(UserRow.login == login))
        return None if row is None else _user(row)

    async def set_password_hash(self, user_id: UUID, password_hash: str) -> None:
        """Replace the hash."""
        await self._session.execute(update(UserRow).where(UserRow.id == user_id).values(password_hash=password_hash))


class SqlSessionRepository:
    """:class:`backend.application.ports.SessionRepository` on PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user_session: UserSession) -> None:
        """Insert."""
        self._session.add(
            SessionRow(
                id_hash=user_session.id_hash,
                user_id=user_session.user_id,
                csrf_token=user_session.csrf_token,
                created_at=user_session.created_at,
                last_seen_at=user_session.last_seen_at,
            ),
        )
        await self._session.flush()

    async def get(self, id_hash: str) -> UserSession | None:
        """By cookie hash."""
        row = await self._session.get(SessionRow, id_hash)
        if row is None:
            return None
        return UserSession(
            id_hash=row.id_hash,
            user_id=row.user_id,
            csrf_token=row.csrf_token,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
        )

    async def touch(self, id_hash: str, moment: datetime) -> None:
        """Extend."""
        await self._session.execute(update(SessionRow).where(SessionRow.id_hash == id_hash).values(last_seen_at=moment))

    async def delete(self, id_hash: str) -> None:
        """Remove."""
        await self._session.execute(delete(SessionRow).where(SessionRow.id_hash == id_hash))


class SqlLoginAttemptRepository:
    """:class:`backend.application.ports.LoginAttemptRepository` on PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, login: str, address: str) -> LoginAttempts | None:
        """Counter of a pair."""
        row = await self._session.get(LoginAttemptRow, (login, address))
        return None if row is None else LoginAttempts(failures=row.failures, locked_until=row.locked_until)

    async def save(self, login: str, address: str, attempts: LoginAttempts, moment: datetime) -> None:
        """Upsert."""
        values = {
            "login": login,
            "address": address,
            "failures": attempts.failures,
            "locked_until": attempts.locked_until,
            "updated_at": moment,
        }
        statement = insert(LoginAttemptRow).values(values)
        statement = statement.on_conflict_do_update(
            index_elements=[LoginAttemptRow.login, LoginAttemptRow.address],
            set_={"failures": attempts.failures, "locked_until": attempts.locked_until, "updated_at": moment},
        )
        await self._session.execute(statement)

    async def clear(self, login: str, address: str) -> None:
        """Reset."""
        await self._session.execute(
            delete(LoginAttemptRow).where(LoginAttemptRow.login == login, LoginAttemptRow.address == address),
        )
