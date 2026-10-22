from urllib.parse import urlsplit

from fastapi import Request

from app.services import auth_service
from app.services.storage_adapters import DomainError


def db(request: Request):
    return request.app.state.db


def now(request: Request):
    return request.app.state.clock()


def origin_check(request: Request):
    origin = request.headers.get("origin", "").rstrip("/")
    expected = str(request.base_url).rstrip("/")
    if origin != expected:
        raise DomainError("ORIGIN_FAILED", "请求来源不受信任，请从本站页面操作。", [], status_code=403)


def identity(request: Request):
    return auth_service.authenticate(db(request), request.cookies.get("survey_session"), now(request))


def require_user(request: Request):
    return identity(request)[0]


def require_write_user(request: Request):
    user, session = identity(request)
    origin_check(request)
    auth_service.verify_csrf(session, request.headers.get("x-csrf-token"))
    return user


def safe_next(value):
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/dashboard"
    parsed = urlsplit(value)
    return value if not parsed.scheme and not parsed.netloc else "/dashboard"
