"""Runtime configuration, read from environment variables only.

Secrets (the database URL, the local administrator's initial password) are referenced by name; no
file is read here, and no value is ever logged or shown in an error message.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

# Local development origin of the Vite dev server (spec, Security model: Allowed origins).
# Deployed environments set CORS_ALLOWED_ORIGINS to their own frontend origin.
DEFAULT_ALLOWED_ORIGINS = "http://localhost:5173"

InstanceMode = Literal["self_hosted", "hosted"]
INSTANCE_MODES: tuple[InstanceMode, ...] = ("self_hosted", "hosted")
DEFAULT_INSTANCE_MODE: InstanceMode = "self_hosted"

# Names of the settings, so that error messages can name them without ever showing a value.
DATABASE_URL = "DATABASE_URL"
CORS_ALLOWED_ORIGINS = "CORS_ALLOWED_ORIGINS"
INSTANCE_MODE = "INSTANCE_MODE"
ADMIN_EMAIL = "ADMIN_EMAIL"
ADMIN_PASSWORD = "ADMIN_PASSWORD"  # noqa: S105 - the name of the setting, not a password
# Path of the approved provider configurations file (#11); the shipped example when unset.
# Provider API keys are read by name in app.providers (KEY_SETTINGS), never stored in Settings.
PROVIDER_CONFIG_FILE = "PROVIDER_CONFIG_FILE"


class ConfigurationError(ValueError):
    """Raised at startup when a configuration value is missing or not acceptable.

    The message names the setting, never its value.
    """


@dataclass(frozen=True)
class Settings:
    # repr=False: the URL can contain the database password.
    database_url: str | None = field(repr=False)
    allowed_origins: tuple[str, ...]
    # "self_hosted" (default) or "hosted". On a self-hosted instance, organisations skip
    # activation (owner decision, 27 Oct 2026; used by #9 and #42).
    instance_mode: InstanceMode = DEFAULT_INSTANCE_MODE
    # The local administrator created on first start (spec, Flow 4). Only read when the
    # database has no user yet; changing them later changes nothing.
    admin_email: str | None = None
    admin_password: str | None = field(default=None, repr=False)
    provider_config_file: str | None = None

    @property
    def organisations_skip_activation(self) -> bool:
        return self.instance_mode == "self_hosted"


def _parse_origins(raw: str) -> tuple[str, ...]:
    origins = tuple(origin.strip() for origin in raw.split(",") if origin.strip())
    if not origins:
        raise ConfigurationError(f"{CORS_ALLOWED_ORIGINS} is set but lists no origin")
    for origin in origins:
        if "*" in origin:
            raise ConfigurationError(f"{CORS_ALLOWED_ORIGINS} must not contain a wildcard")
    return origins


def _parse_instance_mode(raw: str) -> InstanceMode:
    value = raw.strip() or DEFAULT_INSTANCE_MODE
    if value not in INSTANCE_MODES:
        raise ConfigurationError(f"{INSTANCE_MODE} must be one of: {', '.join(INSTANCE_MODES)}")
    return value


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if environ is None else environ
    raw_origins = env.get(CORS_ALLOWED_ORIGINS, "").strip() or DEFAULT_ALLOWED_ORIGINS
    database_url = env.get(DATABASE_URL, "").strip() or None
    return Settings(
        database_url=database_url,
        allowed_origins=_parse_origins(raw_origins),
        instance_mode=_parse_instance_mode(env.get(INSTANCE_MODE, "")),
        admin_email=env.get(ADMIN_EMAIL, "").strip() or None,
        # Not stripped: spaces are valid in a password. Empty means "not set".
        admin_password=env.get(ADMIN_PASSWORD, "") or None,
        provider_config_file=env.get(PROVIDER_CONFIG_FILE, "").strip() or None,
    )
