"""FastAPI dependencies: the container, the signed-in user, CSRF and Origin checks."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from backend.application.views import AuthContext
from backend.composition import Container
from backend.domain.organizations import Actor

SESSION_COOKIE = "ck_session"
CSRF_HEADER = "X-CSRF-Token"


def demo_cookie_name(container: Container) -> str:
    """In production a sibling host cannot set the demo CSRF cookie."""
    return "__Host-ck_demo_csrf" if container.settings.secure_cookies else "ck_demo_csrf"


def get_container(request: Request) -> Container:
    """The application's composition root, created once at startup."""
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


def check_origin(request: Request, container: Container) -> None:
    """Browsers send ``Origin`` with state-changing requests; reject foreign sites."""
    origin = request.headers.get("origin")
    if origin is None:
        return
    own = f"{request.url.scheme}://{request.url.netloc}"
    if origin != own and origin not in container.settings.allowed_origins:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Запрос с чужого сайта отклонён")


async def current_session(request: Request, container: ContainerDep) -> AuthContext:
    """Resolve the session cookie (401 without a valid session)."""
    if container.settings.public_demo:
        return await container.auth.demo_owner(request.cookies.get(demo_cookie_name(container), ""))
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход")
    return await container.auth.authenticate(token)


SessionDep = Annotated[AuthContext, Depends(current_session)]


def current_actor(session: SessionDep) -> Actor:
    """Actor for read-only requests."""
    return Actor(user_id=session.user_id, organization_id=session.organization_id, role=session.role)


async def changing_actor(
    request: Request,
    container: ContainerDep,
    session: SessionDep,
    csrf_token: Annotated[str | None, Header(alias=CSRF_HEADER)] = None,
) -> Actor:
    """Actor for state-changing requests: CSRF token of the session and the Origin must match."""
    check_origin(request, container)
    if not csrf_token or not hmac.compare_digest(csrf_token.encode(), session.csrf_token.encode()):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Недействительный CSRF-токен, обновите страницу")
    return Actor(user_id=session.user_id, organization_id=session.organization_id, role=session.role)


ReaderDep = Annotated[Actor, Depends(current_actor)]
WriterDep = Annotated[Actor, Depends(changing_actor)]
