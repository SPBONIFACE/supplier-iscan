"""Runtime configuration, read from environment variables only.

Secrets (such as the database URL) are referenced by name; no file is read here.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass

# Local development origin of the Vite dev server (spec, Security model: Allowed origins).
# Deployed environments set CORS_ALLOWED_ORIGINS to their own frontend origin.
DEFAULT_ALLOWED_ORIGINS = "http://localhost:5173"


class ConfigurationError(ValueError):
    """Raised at startup when a configuration value is not acceptable."""


@dataclass(frozen=True)
class Settings:
    database_url: str | None
    allowed_origins: tuple[str, ...]


def _parse_origins(raw: str) -> tuple[str, ...]:
    origins = tuple(origin.strip() for origin in raw.split(",") if origin.strip())
    if not origins:
        raise ConfigurationError("CORS_ALLOWED_ORIGINS is set but lists no origin")
    for origin in origins:
        if "*" in origin:
            raise ConfigurationError("CORS_ALLOWED_ORIGINS must not contain a wildcard")
    return origins


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if environ is None else environ
    raw_origins = env.get("CORS_ALLOWED_ORIGINS", "").strip() or DEFAULT_ALLOWED_ORIGINS
    database_url = env.get("DATABASE_URL", "").strip() or None
    return Settings(database_url=database_url, allowed_origins=_parse_origins(raw_origins))
