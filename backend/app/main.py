"""FastAPI application. The API contract is openapi.yaml at the repository root."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError

from app.auth.bootstrap import prepare_database
from app.auth.routes import router as auth_router
from app.config import ConfigurationError, Settings, load_settings
from app.db import Database
from app.errors import install_error_handlers
from app.health import DatabaseCheck, HealthStatus, make_database_check
from app.invitations.log_redaction import install_access_log_redaction
from app.invitations.routes import admin_router as admin_invitations_router
from app.invitations.routes import public_router as invitations_router
from app.organisations.routes import router as admin_organisations_router
from app.providers import Providers, load_catalogue
from app.providers.store import sync_provider_configs
from app.users.routes import router as users_router

logger = logging.getLogger(__name__)


def load_providers(settings: Settings) -> Providers:
    """The approved provider configurations. An invalid file stops startup, naming the file."""
    path = Path(settings.provider_config_file) if settings.provider_config_file else None
    try:
        return Providers(load_catalogue(path))
    except ConfigurationError as error:
        logger.error("Startup stopped: %s", error)
        raise


def create_app(
    settings: Settings | None = None,
    database_check: DatabaseCheck | None = None,
    engine: Engine | None = None,
    providers: Providers | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    check_database = database_check or make_database_check(settings.database_url)
    database = Database(settings.database_url, engine)
    providers = providers or load_providers(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        # Startup: migrations, then the local administrator on first start. A missing setting
        # stops startup with a message that names it. Without DATABASE_URL the API still starts
        # (GET /health answers 503) so that the problem is visible.
        if settings.database_url:
            try:
                prepare_database(database.engine, settings)
                with database.session() as db:
                    sync_provider_configs(db, providers.catalogue)
            except ConfigurationError as error:
                logger.error("Startup stopped: %s", error)
                raise
            except OperationalError:
                # Not the error text: it can contain the connection string.
                logger.error("Startup stopped: the database is unreachable")
                raise
        else:
            logger.warning("DATABASE_URL is not set: migrations and first-start setup skipped")
        missing_settings = providers.missing_settings()
        if missing_settings:
            # Names only: the run cannot start until they are set (GET /health lists them too).
            logger.warning("Provider settings not set: %s", ", ".join(missing_settings))
        yield
        database.dispose()

    # openapi.yaml is the only contract: no generated /openapi.json, no documentation pages.
    app = FastAPI(
        title="Supplier iScan API",
        version="0.4.0",
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.database = database
    app.state.providers = providers
    app.state.settings = settings
    install_access_log_redaction()
    install_error_handlers(app)
    # Exact origins from configuration, never a wildcard (load_settings rejects "*").
    # Credentials are allowed so that the frontend can send the session cookie.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
        allow_credentials=True,
    )

    @app.get(
        "/health",
        response_model=HealthStatus,
        responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthStatus}},
    )
    def get_health(response: Response) -> HealthStatus:
        # Names only, never a value (spec F6: keys never leave configuration).
        missing_settings = providers.missing_settings()
        if check_database():
            return HealthStatus(
                api="available", database="available", missing_settings=missing_settings
            )
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthStatus(
            api="available", database="unavailable", missing_settings=missing_settings
        )

    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(admin_organisations_router)
    app.include_router(admin_invitations_router)
    app.include_router(invitations_router)
    return app


app = create_app()
