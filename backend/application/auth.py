"""Sign-in, sessions and the CLI-only administration of organizations and users."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace

from backend.application.ports import Clock, PasswordHasher, SecretIssuer, UnitOfWork, UnitOfWorkFactory
from backend.application.views import AuthContext, LoginResult
from backend.domain.auth import LoginAttempts, SessionPolicy, ThrottlePolicy, UserSession
from backend.domain.equipment import clean_name
from backend.domain.errors import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    RateLimitedError,
    ValidationFailedError,
)
from backend.domain.organizations import Organization, Role, User

MIN_PASSWORD_LENGTH = 10
MAX_LOGIN_LENGTH = 100
_WRONG_CREDENTIALS = "Неверный логин или пароль"


def normalize_login(login: str) -> str:
    """Logins are case-insensitive and trimmed."""
    return login.strip().lower()


class AuthService:
    """Sessions in the database: sign-out really revokes the session."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        hasher: PasswordHasher,
        secrets: SecretIssuer,
        session_policy: SessionPolicy,
        throttle_policy: ThrottlePolicy,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._hasher = hasher
        self._secrets = secrets
        self._sessions = session_policy
        self._throttle = throttle_policy
        # Verified when the login does not exist, so both cases take the same time.
        self._dummy_hash: str | None = None

    async def login(self, login: str, password: str, address: str) -> LoginResult:
        """Check credentials and open a session; the same error for an unknown login and a wrong password."""
        now = self._clock.now()
        key = normalize_login(login)
        async with self._uow_factory() as uow:
            attempts = await uow.login_attempts.get(key, address)
            if attempts is not None and (remaining := attempts.locked(now)) is not None:
                raise RateLimitedError(
                    "Слишком много неудачных попыток. Попробуйте позже", int(remaining.total_seconds())
                )
            user = await uow.users.get_by_login(key)
            valid = await self._verify(password, user)
            if user is None or not valid or not user.is_active:
                await self._record_failure(uow, key, address, attempts)
                await uow.commit()
                raise AuthenticationError(_WRONG_CREDENTIALS)

            await uow.login_attempts.clear(key, address)
            if self._hasher.needs_rehash(user.password_hash):
                new_hash = await asyncio.to_thread(self._hasher.hash, password)
                await uow.users.set_password_hash(user.id, new_hash)
            token = self._secrets.new_token()
            session = UserSession(
                id_hash=self._secrets.digest(token),
                user_id=user.id,
                csrf_token=self._secrets.new_token(),
                created_at=now,
                last_seen_at=now,
            )
            await uow.sessions.add(session)
            context = await _context(uow, user, session.csrf_token)
            await uow.commit()
        return LoginResult(session_token=token, context=context)

    async def authenticate(self, session_token: str) -> AuthContext:
        """Resolve the session cookie of a request."""
        now = self._clock.now()
        id_hash = self._secrets.digest(session_token)
        async with self._uow_factory() as uow:
            session = await uow.sessions.get(id_hash)
            if session is None:
                raise AuthenticationError("Требуется вход")
            if session.is_expired(now, self._sessions):
                await uow.sessions.delete(id_hash)
                await uow.commit()
                raise AuthenticationError("Сессия истекла, войдите снова")
            user = await uow.users.get(session.user_id)
            if user is None or not user.is_active:
                raise AuthenticationError("Требуется вход")
            if session.needs_touch(now, self._sessions):
                await uow.sessions.touch(id_hash, now)
            context = await _context(uow, user, session.csrf_token)
            await uow.commit()
        return context

    async def logout(self, session_token: str) -> None:
        """Delete the session on the server."""
        async with self._uow_factory() as uow:
            await uow.sessions.delete(self._secrets.digest(session_token))
            await uow.commit()

    async def _verify(self, password: str, user: User | None) -> bool:
        if user is None:
            if self._dummy_hash is None:
                self._dummy_hash = await asyncio.to_thread(self._hasher.hash, "dummy-password-for-timing")
            await asyncio.to_thread(self._hasher.verify, password, self._dummy_hash)
            return False
        return await asyncio.to_thread(self._hasher.verify, password, user.password_hash)

    async def _record_failure(self, uow: UnitOfWork, key: str, address: str, attempts: LoginAttempts | None) -> None:
        now = self._clock.now()
        expired_lock = attempts is not None and attempts.locked_until is not None and attempts.locked_until <= now
        # After a lockout is over, counting starts again.
        previous = 0 if attempts is None or expired_lock else attempts.failures
        failures = previous + 1
        locked_until = now + self._throttle.lockout if failures >= self._throttle.max_failures else None
        await uow.login_attempts.save(key, address, LoginAttempts(failures, locked_until), now)


async def _context(uow: UnitOfWork, user: User, csrf_token: str) -> AuthContext:
    organization = await uow.organizations.get(user.organization_id)
    return AuthContext(
        user_id=user.id,
        organization_id=user.organization_id,
        organization_name=organization.name if organization is not None else "",
        login=user.login,
        role=user.role,
        csrf_token=csrf_token,
    )


class AdminService:
    """Organizations and users are created from the CLI only; there is no public sign-up."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock, hasher: PasswordHasher) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._hasher = hasher

    async def create_organization(self, name: str) -> Organization:
        """New client organization with a unique name."""
        organization = Organization(
            id=uuid.uuid4(),
            name=clean_name(name, "название организации"),
            created_at=self._clock.now(),
        )
        async with self._uow_factory() as uow:
            if await uow.organizations.get_by_name(organization.name) is not None:
                raise ConflictError(f"Организация «{organization.name}» уже существует")
            await uow.organizations.add(organization)
            await uow.commit()
        return organization

    async def get_organization(self, name: str) -> Organization | None:
        """By exact name."""
        async with self._uow_factory() as uow:
            return await uow.organizations.get_by_name(name.strip())

    async def create_user(self, organization_name: str, login: str, password: str, role: Role) -> User:
        """New user of an existing organization."""
        key = normalize_login(login)
        if not key or len(key) > MAX_LOGIN_LENGTH or any(char.isspace() for char in key):
            raise ValidationFailedError("Логин: без пробелов, до 100 символов")
        check_password(password)
        password_hash = await asyncio.to_thread(self._hasher.hash, password)
        async with self._uow_factory() as uow:
            organization = await uow.organizations.get_by_name(organization_name.strip())
            if organization is None:
                raise NotFoundError(f"Организация «{organization_name}» не найдена")
            if await uow.users.get_by_login(key) is not None:
                raise ConflictError(f"Логин «{key}» уже занят")
            user = User(
                id=uuid.uuid4(),
                organization_id=organization.id,
                login=key,
                password_hash=password_hash,
                role=role,
                is_active=True,
                created_at=self._clock.now(),
            )
            await uow.users.add(user)
            await uow.commit()
        return replace(user, password_hash="")

    async def set_password(self, login: str, password: str) -> None:
        """Replace a user's password (CLI; e.g. demo credentials that were lost)."""
        check_password(password)
        password_hash = await asyncio.to_thread(self._hasher.hash, password)
        async with self._uow_factory() as uow:
            user = await uow.users.get_by_login(normalize_login(login))
            if user is None:
                raise NotFoundError(f"Пользователь «{login}» не найден")
            await uow.users.set_password_hash(user.id, password_hash)
            await uow.commit()

    async def get_user(self, login: str) -> User | None:
        """By login (CLI checks)."""
        async with self._uow_factory() as uow:
            return await uow.users.get_by_login(normalize_login(login))


def check_password(password: str) -> None:
    """Length is the only rule; long passphrases are welcome."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationFailedError(f"Пароль — не короче {MIN_PASSWORD_LENGTH} символов")
