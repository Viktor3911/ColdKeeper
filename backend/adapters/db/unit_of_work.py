"""Unit of work on one ``AsyncSession``: commit is explicit, everything else is rolled back."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from backend.adapters.db.accounts import (
    SqlLoginAttemptRepository,
    SqlOrganizationRepository,
    SqlSessionRepository,
    SqlUserRepository,
)
from backend.adapters.db.inventory import SqlInventoryRepository
from backend.adapters.db.measurements import SqlMeasurementRepository
from backend.adapters.db.monitoring import SqlIncidentRepository, SqlPointStateRepository
from backend.adapters.db.notifications import SqlNotificationRepository, SqlRecipientRepository
from backend.adapters.db.sensors import SqlAssignmentRepository, SqlSensorRepository


def create_engine(url: str, *, echo: bool = False) -> AsyncEngine:
    """Async engine with connection health checks."""
    return create_async_engine(url, echo=echo, pool_pre_ping=True)


def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Sessions that keep loaded values after commit (repositories return detached domain objects anyway)."""
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


class SqlUnitOfWork:
    """:class:`backend.application.ports.UnitOfWork` on PostgreSQL."""

    organizations: SqlOrganizationRepository
    users: SqlUserRepository
    sessions: SqlSessionRepository
    login_attempts: SqlLoginAttemptRepository
    inventory: SqlInventoryRepository
    sensors: SqlSensorRepository
    assignments: SqlAssignmentRepository
    measurements: SqlMeasurementRepository
    point_states: SqlPointStateRepository
    incidents: SqlIncidentRepository
    recipients: SqlRecipientRepository
    notifications: SqlNotificationRepository

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> SqlUnitOfWork:
        """Open a session and bind the repositories to it."""
        session = self._sessions()
        self._session = session
        self.organizations = SqlOrganizationRepository(session)
        self.users = SqlUserRepository(session)
        self.sessions = SqlSessionRepository(session)
        self.login_attempts = SqlLoginAttemptRepository(session)
        self.inventory = SqlInventoryRepository(session)
        self.sensors = SqlSensorRepository(session)
        self.assignments = SqlAssignmentRepository(session)
        self.measurements = SqlMeasurementRepository(session)
        self.point_states = SqlPointStateRepository(session)
        self.incidents = SqlIncidentRepository(session)
        self.recipients = SqlRecipientRepository(session)
        self.notifications = SqlNotificationRepository(session)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        """Roll back what was not committed and release the connection."""
        if self._session is not None:
            await self._session.rollback()
            await self._session.close()
            self._session = None

    async def commit(self) -> None:
        """Commit."""
        if self._session is None:
            msg = "unit of work is not active"
            raise RuntimeError(msg)
        await self._session.commit()


class SqlUnitOfWorkFactory:
    """:class:`backend.application.ports.UnitOfWorkFactory` bound to one engine."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    def __call__(self) -> SqlUnitOfWork:
        """New unit of work."""
        return SqlUnitOfWork(self._sessions)
