from contextlib import asynccontextmanager
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pymongo.errors import PyMongoError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import __version__
from app.api import auth, participation, statistics, surveys
from app.api.dependencies import identity, safe_next
from app.config import ROOT, Settings
from app.database import connect, initialize_database, utcnow
from app.services.storage_adapters import DomainError


def create_app(settings=None, database=None, clock=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(application):
        if database is None:
            application.state.mongo_client = connect(settings.mongodb_uri)
            application.state.db = application.state.mongo_client[settings.mongodb_db]
        application.state.db.command("ping")
        initialize_database(application.state.db)
        yield
        if database is None:
            application.state.mongo_client.close()

    application = FastAPI(title="问卷工坊 API", version=__version__, lifespan=lifespan)
    application.state.settings = settings
    application.state.clock = clock or utcnow
    if database is not None:
        application.state.db = database
    allowed = ["127.0.0.1", "localhost", urlsplit(settings.app_origin).hostname or "127.0.0.1"]
    if settings.testing:
        allowed.append("testserver")
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed)

    @application.middleware("http")
    async def request_limits(request, call_next):
        if request.url.path.startswith("/api/") and request.method in {"POST", "PATCH", "PUT", "DELETE"}:
            length = request.headers.get("content-length", "0")
            if not length.isdigit() or int(length) > 1024*1024:
                return JSONResponse({"error": {"code": "REQUEST_TOO_LARGE", "message": "请求内容过大。", "details": []}}, status_code=413)
            if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
                return JSONResponse({"error": {"code": "JSON_REQUIRED", "message": "请使用 JSON 请求。", "details": []}}, status_code=415)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(DomainError)
    async def domain_error(request, error):
        return JSONResponse({"error": {"code": error.code, "message": error.message, "details": error.details}}, status_code=error.status_code)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        details = [{"field": ".".join(str(v) for v in item["loc"]), "message": item["msg"]} for item in error.errors()]
        return JSONResponse({"error": {"code": "INVALID_REQUEST", "message": "请求字段不正确。", "details": details}}, status_code=422)

    @application.exception_handler(PyMongoError)
    async def database_error(request, error):
        return JSONResponse({"error": {"code": "DATABASE_UNAVAILABLE", "message": "数据库暂时不可用，请稍后重试。", "details": []}}, status_code=503)

    for router in [auth.router, surveys.router, participation.router, statistics.router]:
        application.include_router(router)
    application.mount("/static", StaticFiles(directory=ROOT / "app" / "static", check_dir=False), name="static")
    templates = Jinja2Templates(directory=ROOT / "app" / "templates")

    def page(request, name, template, **context):
        try:
            user, session = identity(request)
        except DomainError:
            user = None
        if name not in {"login", "register"} and user is None:
            return RedirectResponse("/login?next="+quote(request.url.path, safe=""), status_code=303)
        if name in {"login", "register"} and user:
            return RedirectResponse(safe_next(request.query_params.get("next")), status_code=303)
        return templates.TemplateResponse(request=request, name=template, context={"page": name, "next": safe_next(request.query_params.get("next")), "user": user, **context})

    @application.get("/", include_in_schema=False)
    def home(request: Request):
        return RedirectResponse("/dashboard", status_code=303)

    @application.get("/login", include_in_schema=False)
    def login_page(request: Request):
        return page(request, "login", "auth.html")

    @application.get("/register", include_in_schema=False)
    def register_page(request: Request):
        return page(request, "register", "auth.html")

    @application.get("/dashboard", include_in_schema=False)
    def dashboard_page(request: Request):
        return page(request, "dashboard", "dashboard.html")

    @application.get("/surveys/{survey_id}/edit", include_in_schema=False)
    def editor_page(survey_id: str, request: Request):
        return page(request, "editor", "editor.html", survey_id=survey_id)

    @application.get("/surveys/{survey_id}/preview", include_in_schema=False)
    def preview_page(survey_id: str, request: Request):
        return page(request, "preview", "fill.html", survey_id=survey_id)

    @application.get("/surveys/{survey_id}/statistics", include_in_schema=False)
    def statistics_page(survey_id: str, request: Request):
        return page(request, "statistics", "statistics.html", survey_id=survey_id)

    @application.get("/survey/{public_id}", include_in_schema=False)
    def fill_page(public_id: str, request: Request):
        return page(request, "fill", "fill.html", public_id=public_id)

    @application.get("/health", tags=["运行状态"])
    def health(request: Request):
        request.app.state.db.command("ping")
        return {"status": "ok", "database": "connected", "version": __version__}

    return application


app = create_app()
