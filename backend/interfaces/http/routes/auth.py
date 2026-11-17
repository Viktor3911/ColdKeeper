"""Sign-in, sign-out and the current session."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from backend.interfaces.http.dependencies import SESSION_COOKIE, ContainerDep, SessionDep, WriterDep, check_origin
from backend.interfaces.http.schemas import ErrorOut, LoginIn, SessionOut

router = APIRouter(prefix="/api/v1", tags=["auth"])


def client_address(request: Request) -> str:
    """Client IP; behind the proxy uvicorn takes it from trusted forwarded headers only."""
    return request.client.host if request.client else "unknown"


@router.post(
    "/auth/login",
    responses={401: {"model": ErrorOut}, 429: {"model": ErrorOut}},
)
async def login(body: LoginIn, request: Request, response: Response, container: ContainerDep) -> SessionOut:
    """Open a session: HttpOnly cookie + CSRF token in the body."""
    check_origin(request, container)
    result = await container.auth.login(body.login, body.password, client_address(request))
    settings = container.settings
    response.set_cookie(
        SESSION_COOKIE,
        result.session_token,
        max_age=settings.session_absolute_days * 24 * 3600,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )
    return SessionOut.of(result.context)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, container: ContainerDep, _actor: WriterDep) -> Response:
    """Delete the session on the server and the cookie in the browser."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await container.auth.logout(token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE, path="/", secure=container.settings.secure_cookies, httponly=True)
    return response


@router.get("/session", responses={401: {"model": ErrorOut}})
async def session(current: SessionDep) -> SessionOut:
    """Current user (the frontend calls it after a reload to get the CSRF token)."""
    return SessionOut.of(current)
