"""Runtime configuration, read from environment variables only.

Secrets (the database URL, the local administrator's initial password) are referenced by name; no
file is read here, and no value is ever logged or shown in an error message.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal
from urllib.parse import urlsplit

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
# Price table (#12): prices per model with an "as of" date; the shipped example when unset.
# Providers bill in USD and costs are shown in EUR, so the conversion rate is a setting
# (EUR for 1 USD).
PRICE_TABLE_FILE = "PRICE_TABLE_FILE"
# Profile definition (#21): sections and fields of a profile; the shipped example when unset.
PROFILE_DEFINITION_FILE = "PROFILE_DEFINITION_FILE"
# Prompt set (#55): the instructions of the LLM features; the shipped example when unset.
PROMPT_SET_FILE = "PROMPT_SET_FILE"
# Financial country table (#26): registries and document access per country; the shipped example
# (clearly marked, rows not verified) when unset. The real table is the owner's.
COUNTRY_TABLE_FILE = "COUNTRY_TABLE_FILE"
# Longest texts a member may enter for a profile (#26): the fit criteria (all together), the notes
# of the buyer context, and a buyer field.
CRITERIA_MAX_CHARS = "CRITERIA_MAX_CHARS"
BUYER_NOTES_MAX_CHARS = "BUYER_NOTES_MAX_CHARS"
BUYER_TEXT_MAX_CHARS = "BUYER_TEXT_MAX_CHARS"
# The longest corrected value of a fact or corrected text of a statement (#28).
REVIEW_TEXT_MAX_CHARS = "REVIEW_TEXT_MAX_CHARS"
# Disclaimer printed on the supplier card PDF (#39): owner-supplied text, EN and FR; a marked
# placeholder (the shipped example) when unset.
PDF_DISCLAIMER_FILE = "PDF_DISCLAIMER_FILE"
# The most profiles one side-by-side comparison accepts (#38, owner decision, 27 Oct 2026).
COMPARISON_MAX_PROFILES = "COMPARISON_MAX_PROFILES"
EUR_PER_USD = "EUR_PER_USD"
INVITATION_VALIDITY_HOURS = "INVITATION_VALIDITY_HOURS"
PASSWORD_MIN_LENGTH = "PASSWORD_MIN_LENGTH"  # noqa: S105 - the name of the setting
# Job queue (#13): how long a worker holds a job before another may reclaim it, and how often an
# idle worker looks for work.
RUN_LEASE_SECONDS = "RUN_LEASE_SECONDS"
WORKER_POLL_SECONDS = "WORKER_POLL_SECONDS"
# Crawler identity (#17): the public contact page named in the User-Agent of every request to a
# supplier site. No default: the operator publishes their own page (#47).
CRAWLER_CONTACT_URL = "CRAWLER_CONTACT_URL"
# Monthly LLM spend cap of the instance, in EUR (spec F7). Unset: no cap.
MONTHLY_SPEND_CAP_EUR = "MONTHLY_SPEND_CAP_EUR"
# Hard cost budget of one profile run, in EUR (spec F7, #30). Always on, on a self-hosted
# instance too, and with no default: the operator chooses it (a missing, zero or negative value
# stops startup). The most retries of one provider call after a schema failure.
RUN_BUDGET_EUR = "RUN_BUDGET_EUR"
PROVIDER_MAX_RETRIES = "PROVIDER_MAX_RETRIES"

# Local defaults when the setting is empty, so that a self-hosted instance starts without them.
# They are configuration, not product terms: every operator sets their own.
DEFAULT_INVITATION_VALIDITY_HOURS = 72
DEFAULT_PASSWORD_MIN_LENGTH = 12
DEFAULT_RUN_LEASE_SECONDS = 300
DEFAULT_WORKER_POLL_SECONDS = 2
DEFAULT_CRITERIA_MAX_CHARS = 2000
DEFAULT_BUYER_NOTES_MAX_CHARS = 1000
DEFAULT_BUYER_TEXT_MAX_CHARS = 5000
DEFAULT_PROVIDER_MAX_RETRIES = 1
MAX_PROVIDER_RETRIES = 5
DEFAULT_REVIEW_TEXT_MAX_CHARS = 2000
DEFAULT_COMPARISON_MAX_PROFILES = 10
MIN_COMPARISON_MAX_PROFILES = 2
MAX_SETTING_NUMBER = 100_000
MAX_RUN_BUDGET_EUR = Decimal(100_000)


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
    price_table_file: str | None = None
    profile_definition_file: str | None = None
    prompt_set_file: str | None = None
    country_table_file: str | None = None
    pdf_disclaimer_file: str | None = None
    criteria_max_chars: int = DEFAULT_CRITERIA_MAX_CHARS
    buyer_notes_max_chars: int = DEFAULT_BUYER_NOTES_MAX_CHARS
    buyer_text_max_chars: int = DEFAULT_BUYER_TEXT_MAX_CHARS
    review_text_max_chars: int = DEFAULT_REVIEW_TEXT_MAX_CHARS
    comparison_max_profiles: int = DEFAULT_COMPARISON_MAX_PROFILES
    eur_per_usd: Decimal | None = None
    # How long an invitation link stays valid, and the shortest accepted password (#9).
    invitation_validity: timedelta = timedelta(hours=DEFAULT_INVITATION_VALIDITY_HOURS)
    password_min_length: int = DEFAULT_PASSWORD_MIN_LENGTH
    run_lease: timedelta = timedelta(seconds=DEFAULT_RUN_LEASE_SECONDS)
    worker_poll_seconds: int = DEFAULT_WORKER_POLL_SECONDS
    crawler_contact_url: str | None = None
    monthly_spend_cap_eur: Decimal | None = None
    # None when unset: `load_providers` then stops startup (see `require_run_budget`).
    run_budget_eur: Decimal | None = None
    provider_max_retries: int = DEFAULT_PROVIDER_MAX_RETRIES

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


def _parse_positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    # A technical bound only (it keeps date arithmetic in range), not a product term.
    if not (raw.isascii() and raw.isdigit()) or not 1 <= int(raw) <= MAX_SETTING_NUMBER:
        raise ConfigurationError(
            f"{name} must be a whole number between 1 and {MAX_SETTING_NUMBER}"
        )
    return int(raw)


def _parse_comparison_max(raw: str) -> int:
    value = raw.strip()
    if not value:
        return DEFAULT_COMPARISON_MAX_PROFILES
    if (
        not (value.isascii() and value.isdigit())
        or not MIN_COMPARISON_MAX_PROFILES <= int(value) <= MAX_SETTING_NUMBER
    ):
        raise ConfigurationError(
            f"{COMPARISON_MAX_PROFILES} must be a whole number between "
            f"{MIN_COMPARISON_MAX_PROFILES} and {MAX_SETTING_NUMBER}"
        )
    return int(value)


def _parse_contact_url(raw: str) -> str | None:
    value = raw.strip()
    if not value:
        return None
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username:
        raise ConfigurationError(f"{CRAWLER_CONTACT_URL} must be an http(s) address")
    if any(
        character.isspace() or character in "()<>" or ord(character) < 32 for character in value
    ):
        raise ConfigurationError(f"{CRAWLER_CONTACT_URL} must be an http(s) address")
    return value


def _parse_rate(raw: str) -> Decimal | None:
    value = raw.strip()
    if not value:
        return None
    try:
        rate = Decimal(value)
    except InvalidOperation:
        rate = Decimal(0)
    if not rate.is_finite() or not Decimal("0.01") <= rate <= Decimal(100):
        raise ConfigurationError(f"{EUR_PER_USD} must be a number between 0.01 and 100")
    return rate


def _parse_spend_cap(raw: str) -> Decimal | None:
    value = raw.strip()
    if not value:
        return None
    try:
        cap = Decimal(value)
    except InvalidOperation:
        cap = Decimal(0)
    if not cap.is_finite() or cap <= 0:
        raise ConfigurationError(f"{MONTHLY_SPEND_CAP_EUR} must be a number above 0")
    return cap


def _parse_run_budget(raw: str) -> Decimal | None:
    value = raw.strip()
    if not value:
        return None
    try:
        budget = Decimal(value)
    except InvalidOperation:
        budget = Decimal(0)
    if not budget.is_finite() or not 0 < budget <= MAX_RUN_BUDGET_EUR:
        raise ConfigurationError(f"{RUN_BUDGET_EUR} must be a number above 0 and at most 100000")
    return budget


def _parse_max_retries(raw: str) -> int:
    value = raw.strip()
    if not value:
        return DEFAULT_PROVIDER_MAX_RETRIES
    if not value.isascii() or not value.isdigit() or int(value) > MAX_PROVIDER_RETRIES:
        raise ConfigurationError(
            f"{PROVIDER_MAX_RETRIES} must be a whole number between 0 and {MAX_PROVIDER_RETRIES}"
        )
    return int(value)


def require_run_budget(settings: "Settings") -> Decimal:
    """The per-run budget in EUR; a missing one stops startup (owner decision, 27 Oct 2026: the
    budget always applies, on a self-hosted instance too)."""
    if settings.run_budget_eur is None:
        raise ConfigurationError(f"{RUN_BUDGET_EUR} must be set to a number above 0")
    return settings.run_budget_eur


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
        price_table_file=env.get(PRICE_TABLE_FILE, "").strip() or None,
        profile_definition_file=env.get(PROFILE_DEFINITION_FILE, "").strip() or None,
        prompt_set_file=env.get(PROMPT_SET_FILE, "").strip() or None,
        country_table_file=env.get(COUNTRY_TABLE_FILE, "").strip() or None,
        pdf_disclaimer_file=env.get(PDF_DISCLAIMER_FILE, "").strip() or None,
        criteria_max_chars=_parse_positive_int(env, CRITERIA_MAX_CHARS, DEFAULT_CRITERIA_MAX_CHARS),
        buyer_notes_max_chars=_parse_positive_int(
            env, BUYER_NOTES_MAX_CHARS, DEFAULT_BUYER_NOTES_MAX_CHARS
        ),
        buyer_text_max_chars=_parse_positive_int(
            env, BUYER_TEXT_MAX_CHARS, DEFAULT_BUYER_TEXT_MAX_CHARS
        ),
        review_text_max_chars=_parse_positive_int(
            env, REVIEW_TEXT_MAX_CHARS, DEFAULT_REVIEW_TEXT_MAX_CHARS
        ),
        comparison_max_profiles=_parse_comparison_max(env.get(COMPARISON_MAX_PROFILES, "")),
        eur_per_usd=_parse_rate(env.get(EUR_PER_USD, "")),
        invitation_validity=timedelta(
            hours=_parse_positive_int(
                env, INVITATION_VALIDITY_HOURS, DEFAULT_INVITATION_VALIDITY_HOURS
            )
        ),
        password_min_length=_parse_positive_int(
            env, PASSWORD_MIN_LENGTH, DEFAULT_PASSWORD_MIN_LENGTH
        ),
        run_lease=timedelta(
            seconds=_parse_positive_int(env, RUN_LEASE_SECONDS, DEFAULT_RUN_LEASE_SECONDS)
        ),
        worker_poll_seconds=_parse_positive_int(
            env, WORKER_POLL_SECONDS, DEFAULT_WORKER_POLL_SECONDS
        ),
        crawler_contact_url=_parse_contact_url(env.get(CRAWLER_CONTACT_URL, "")),
        monthly_spend_cap_eur=_parse_spend_cap(env.get(MONTHLY_SPEND_CAP_EUR, "")),
        run_budget_eur=_parse_run_budget(env.get(RUN_BUDGET_EUR, "")),
        provider_max_retries=_parse_max_retries(env.get(PROVIDER_MAX_RETRIES, "")),
    )
