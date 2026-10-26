"""FastAPI application factory.  Run:  cd backend && uvicorn app.main:app --port 8000   (serves the API and the frontend) — see README."""
from __future__ import annotations

import contextlib
import json
import logging
import os
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .config import Settings
from .services.history import HistoryStore
from .services.model_service import ModelService, ServiceError


class _JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"), "level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__      # type only: no stack trace in structured logs
        return json.dumps(payload)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger("ucp")
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    root.propagate = False


class BodySizeLimit:
    """Pure-ASGI request-size limit (Content-Length check plus streamed byte counting)."""

    def __init__(self, app, max_bytes: int):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        too_big = JSONResponse({"error": {"code": "payload_too_large", "message": "Request body too large.", "details": {}}}, status_code=413)
        try:
            if int(headers.get(b"content-length", b"0")) > self.max_bytes:
                return await too_big(scope, receive, send)
        except ValueError:
            return await too_big(scope, receive, send)
        seen = 0

        async def limited():
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > self.max_bytes:
                    raise ServiceError("payload_too_large", "Request body too large.", 413)
            return msg
        return await self.app(scope, limited, send)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    settings = app.state.settings
    is_prod = os.environ.get("ENVIRONMENT", "").lower() == "production" or os.environ.get("ENV", "").lower() == "production"
    if settings.history_salt == "change-me":
        if is_prod:
            raise RuntimeError("HISTORY_SALT must not be left at default value 'change-me' in production.")
        logging.getLogger("ucp").warning("HISTORY_SALT is using the default 'change-me' value. Set HISTORY_SALT in production.")
    yield
    if hasattr(app.state, "history") and hasattr(app.state.history, "close"):
        app.state.history.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    configure_logging(settings.log_level)
    log = logging.getLogger("ucp.http")
    app = FastAPI(title="Used Car Price Prediction API", version="1.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.state.service = ModelService(settings.models_dir, settings.ml_dir)
    app.state.history = HistoryStore(settings.db_path, settings.history_salt, settings.history_limit)

    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST", "DELETE"],
                       allow_headers=["Content-Type", "X-Client-Id"], max_age=600)
    app.add_middleware(BodySizeLimit, max_bytes=settings.max_body_bytes)

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        start, rid = time.perf_counter(), uuid.uuid4().hex[:12]
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api"):
            log.info("%s %s -> %s %.0fms rid=%s", request.method, request.url.path, response.status_code, (time.perf_counter() - start) * 1000, rid)
        return response

    def err(code, message, status, details=None):
        return JSONResponse({"error": {"code": code, "message": message, "details": details or {}}}, status_code=status)

    @app.exception_handler(ServiceError)
    async def service_error(_: Request, exc: ServiceError):
        return err(exc.code, exc.message, exc.status, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        fields = [{"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]} for e in exc.errors()]
        return err("validation_error", "Some inputs are missing or out of range.", 422, {"fields": fields})

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        logging.getLogger("ucp.http").error("unhandled_error type=%s", type(exc).__name__)
        return err("internal_error", "Something went wrong. Please try again.", 500)

    app.include_router(router)
    if settings.frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
    return app


app = create_app()
