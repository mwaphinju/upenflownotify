import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from sqlalchemy import select

from app.auth import router as auth_router
from app.accounts import router as accounts_router
from app.sending import router as sending_router
from app.messages import router as messages_router
from app.configuration import router as configuration_router
from app.service_b import reply_router as service_b_reply_router, router as delivery_reports_router
from app.blocklist import router as blocklist_router
from app.config import Settings, get_settings
from app.database import Base, build_engine, build_session_factory
from app.logging_config import configure_logging
from app.models import User
from app.monitoring import scheduler_loop
from app.rules import router as rules_router
from app.security import hash_password

configure_logging()
logger = logging.getLogger("upenflow.http")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.auto_create_schema:
            Base.metadata.create_all(engine)
        if settings.first_admin_email and settings.first_admin_password:
            with session_factory() as db:
                admin_email = settings.first_admin_email.lower()
                existing = db.scalar(select(User).where(User.email == admin_email))
                if existing is None:
                    db.add(
                        User(
                            name=settings.first_admin_name,
                            email=admin_email,
                            password_hash=hash_password(settings.first_admin_password),
                            role="super_admin",
                            is_active=True,
                        )
                    )
                    db.commit()
        scheduler_task = None
        if settings.enable_scheduler:
            scheduler_task = asyncio.create_task(scheduler_loop(session_factory, settings))
        yield
        if scheduler_task:
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                pass
        engine.dispose()

    app = FastAPI(title="Upenflow Notify", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.include_router(auth_router)
    app.include_router(accounts_router)
    app.include_router(sending_router)
    app.include_router(messages_router)
    app.include_router(configuration_router)
    app.include_router(delivery_reports_router)
    app.include_router(service_b_reply_router)
    app.include_router(blocklist_router)
    app.include_router(rules_router)

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        started = time.monotonic()
        response = await call_next(request)
        logger.info(
            "http_request",
            extra={
                "fields": {
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round((time.monotonic() - started) * 1000, 1),
                }
            },
        )
        return response

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # Only honoured by browsers when the response is actually served over HTTPS
        # (e.g. behind a TLS-terminating reverse proxy); harmless to send over plain HTTP.
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        return {"status": "ready"}

    return app


app = create_app()