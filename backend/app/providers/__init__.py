"""LLM providers: the single path from the application to a vendor API.

Vendor SDKs are imported only inside this package (a test enforces it). Feature code uses:

- `Providers` (`app.state.providers`): `.structuring()` / `.retrieval()` return a client bound to
  the approved configuration selected for the role; `.check_ready()` at run start;
  `.missing_settings()` for `GET /health`.
- `StructuringClient.structure(request, OutputSchema)` and `RetrievalClient.retrieve(request)`.
- The typed errors of `app.providers.errors`.
"""

from app.providers.catalogue import (
    KEY_SETTINGS,
    ROLES,
    ProviderCatalogue,
    ProviderConfigSpec,
    Role,
    load_catalogue,
)
from app.providers.errors import (
    ProviderCallError,
    ProviderConfigurationRefused,
    ProviderError,
    ProvidersNotReady,
    ProviderSettingMissing,
    StructuredOutputInvalid,
)
from app.providers.interface import (
    RetrievalClient,
    RetrievalRequest,
    RetrievalResult,
    RetrievedUrl,
    StructuringClient,
    StructuringRequest,
)
from app.providers.registry import Providers

__all__ = [
    "KEY_SETTINGS",
    "ROLES",
    "ProviderCallError",
    "ProviderCatalogue",
    "ProviderConfigSpec",
    "ProviderConfigurationRefused",
    "ProviderError",
    "ProviderSettingMissing",
    "Providers",
    "ProvidersNotReady",
    "RetrievalClient",
    "RetrievalRequest",
    "RetrievalResult",
    "RetrievedUrl",
    "Role",
    "StructuredOutputInvalid",
    "StructuringClient",
    "StructuringRequest",
    "load_catalogue",
]
