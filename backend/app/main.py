"""FastAPI application. The API contract is openapi.yaml at the repository root."""

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, load_settings
from app.health import DatabaseCheck, HealthStatus, make_database_check


def create_app(
    settings: Settings | None = None, database_check: DatabaseCheck | None = None
) -> FastAPI:
    settings = settings or load_settings()
    check_database = database_check or make_database_check(settings.database_url)

    # openapi.yaml is the contract: the interactive documentation pages are disabled.
    app = FastAPI(title="Supplier iScan API", version="0.1.0", docs_url=None, redoc_url=None)
    # Exact origins from configuration, never a wildcard (load_settings rejects "*").
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_methods=["GET"],
    )

    @app.get(
        "/health",
        response_model=HealthStatus,
        responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthStatus}},
    )
    def get_health(response: Response) -> HealthStatus:
        if check_database():
            return HealthStatus(api="available", database="available")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthStatus(api="available", database="unavailable")

    return app


app = create_app()
