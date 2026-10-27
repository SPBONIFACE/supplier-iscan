"""Typed errors of the provider interface.

Every message names the provider and the configuration and gives a plain-language reason. None
ever contains an API key, a prompt or a response: messages are built from fixed texts, never from
the text of a vendor SDK exception (which can quote the request or the response body).
"""

from typing import Literal

FailureKind = Literal[
    "timeout",
    "connection",
    "authentication",
    "rate_limited",
    "rejected",
    "unavailable",
    "invalid_response",
    "unexpected",
]

FAILURE_REASONS: dict[FailureKind, str] = {
    "timeout": "The provider did not answer in time.",
    "connection": "The provider could not be reached.",
    "authentication": "The provider refused the API key (missing permission, invalid or revoked key).",
    "rate_limited": "The provider is limiting requests for now.",
    "rejected": "The provider rejected the request.",
    "unavailable": "The provider is temporarily unavailable.",
    "invalid_response": "The provider returned an answer that could not be read.",
    "unexpected": "The provider call failed unexpectedly.",
}


class ProviderError(Exception):
    """Base class. `retryable` tells the caller whether trying the same call again can succeed."""

    retryable: bool = False

    def __init__(self, *, provider: str | None, config_id: str, reason: str) -> None:
        self.provider = provider
        self.config_id = config_id
        self.reason = reason
        super().__init__(self._message())

    def _message(self) -> str:
        provider = self.provider or "unknown provider"
        return f"{provider}, configuration {self.config_id!r}: {self.reason}"


class ProviderCallError(ProviderError):
    """The provider call failed: timeout, connection, HTTP 4xx/5xx, refused key. The run can retry."""

    retryable = True

    def __init__(
        self,
        *,
        provider: str,
        config_id: str,
        kind: FailureKind,
        status_code: int | None = None,
    ) -> None:
        self.kind = kind
        self.status_code = status_code
        reason = FAILURE_REASONS[kind]
        if status_code is not None:
            reason = f"{reason} (HTTP {status_code})"
        super().__init__(provider=provider, config_id=config_id, reason=reason)


class ProviderConfigurationRefused(ProviderError):
    """The configuration is unknown, disabled, unverified, or does not support the role.

    Raised before any network call. No other configuration is tried (no fallback): an
    administrator must fix the configuration.
    """


class ProviderSettingMissing(ProviderError):
    """The API key setting of the selected configuration is not set. Names the setting only."""

    def __init__(self, *, provider: str, config_id: str, setting: str) -> None:
        self.setting = setting
        super().__init__(
            provider=provider, config_id=config_id, reason=f"the setting {setting} is not set."
        )


class StructuredOutputInvalid(ProviderError):
    """The output did not validate against its schema, on the first try and on the retry."""

    retryable = True

    def __init__(self, *, provider: str, config_id: str, schema_name: str, attempts: int) -> None:
        self.schema_name = schema_name
        self.attempts = attempts
        super().__init__(
            provider=provider,
            config_id=config_id,
            reason=(
                f"the output did not match the {schema_name} schema "
                f"after {attempts} attempts and was dropped."
            ),
        )


class ProvidersNotReady(Exception):
    """Run start: a selected configuration cannot be used. Lists every problem, by name only."""

    def __init__(self, problems: list[ProviderError]) -> None:
        self.problems = problems
        super().__init__("; ".join(str(problem) for problem in problems))

    @property
    def missing_settings(self) -> list[str]:
        return sorted(
            {problem.setting for problem in self.problems if isinstance(problem, ProviderSettingMissing)}
        )
