import hashlib
import hmac
import secrets
import unicodedata
from datetime import timedelta

from pwdlib import PasswordHash
from pymongo.errors import DuplicateKeyError

from app.services.storage_adapters import DomainError

PASSWORDS = PasswordHash.recommended()
_DUMMY_HASH = PASSWORDS.hash("dummy-password-for-nonexistent-user")


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def public_user(user):
    return {"id": str(user["_id"]), "username": user["username"], "createdAt": user["createdAt"].isoformat()}


def register(db, username, password, now):
    username = unicodedata.normalize("NFC", username.strip())
    if not 3 <= len(username) <= 32:
        raise DomainError("INVALID_USERNAME", "用户名长度须为 3–32 个字符。", [{"field": "username"}])
    if not 8 <= len(password) <= 128:
        raise DomainError("INVALID_PASSWORD", "密码长度须为 8–128 个字符。", [{"field": "password"}])
    user = {"username": username, "usernameNormalized": username.casefold(), "passwordHash": PASSWORDS.hash(password), "createdAt": now, "schemaVersion": 1}
    try:
        user["_id"] = db.users.insert_one(user).inserted_id
    except DuplicateKeyError:
        raise DomainError("USERNAME_EXISTS", "该用户名已被注册。", [], status_code=409)
    return user


def login(db, username, password, now, ttl):
    normalized = unicodedata.normalize("NFC", username.strip()).casefold()
    user = db.users.find_one({"usernameNormalized": normalized})
    try:
        verified = PASSWORDS.verify(password, user["passwordHash"] if user else _DUMMY_HASH)
    except (ValueError, TypeError):
        verified = False
    if not user or not verified:
        raise DomainError("INVALID_CREDENTIALS", "用户名或密码不正确。", [], status_code=401)
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    session = {"tokenHash": digest(token), "csrfTokenHash": digest(csrf), "userId": user["_id"], "createdAt": now, "expiresAt": now + timedelta(seconds=ttl)}
    db.sessions.insert_one(session)
    return user, token, csrf


def authenticate(db, token, now):
    if not token:
        raise DomainError("AUTH_REQUIRED", "请先登录。", [], status_code=401)
    session = db.sessions.find_one({"tokenHash": digest(token), "expiresAt": {"$gt": now}})
    user = db.users.find_one({"_id": session["userId"]}) if session else None
    if not user:
        raise DomainError("AUTH_REQUIRED", "登录已失效，请重新登录。", [], status_code=401)
    return user, session


def verify_csrf(session, value):
    if not value or not hmac.compare_digest(session["csrfTokenHash"], digest(value)):
        raise DomainError("CSRF_FAILED", "请求校验失效，请刷新页面后重试。", [], status_code=403)
