from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.dependencies import db, now, origin_check, require_user, require_write_user
from app.schemas.requests import Credentials
from app.services import auth_service

router = APIRouter(prefix="/api/auth", tags=["用户认证"])


@router.post("/register", status_code=201)
def register(payload: Credentials, request: Request):
    origin_check(request)
    user = auth_service.register(db(request), payload.username, payload.password, now(request))
    return {"user": auth_service.public_user(user)}


@router.post("/login")
def login(payload: Credentials, request: Request):
    origin_check(request)
    settings = request.app.state.settings
    user, token, csrf = auth_service.login(db(request), payload.username, payload.password, now(request), settings.session_ttl_seconds)
    result = JSONResponse({"user": auth_service.public_user(user)})
    for name, value, http_only in [("survey_session", token, True), ("csrf_token", csrf, False)]:
        result.set_cookie(name, value, max_age=settings.session_ttl_seconds, httponly=http_only, secure=settings.cookie_secure, samesite="lax", path="/")
    return result


@router.get("/me")
def me(user=Depends(require_user)):
    return {"user": auth_service.public_user(user)}


@router.post("/logout")
def logout(request: Request, user=Depends(require_write_user)):
    db(request).sessions.delete_one({"tokenHash": auth_service.digest(request.cookies["survey_session"])})
    result = JSONResponse({"ok": True})
    result.delete_cookie("survey_session", path="/")
    result.delete_cookie("csrf_token", path="/")
    return result
