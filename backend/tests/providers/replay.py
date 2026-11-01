"""Build the real adapter of a configuration on a given HTTP client (replay or recording).

The contract tests give it a mock transport that replays a recording; the re-record command gives
it a transport that really calls the provider. Same adapter code in both.
"""

import json
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import patch

import httpx
import httpx2

from app.providers.adapters import ADAPTERS
from app.providers.catalogue import ProviderConfigSpec, Role

RECORDINGS = Path(__file__).resolve().parent / "recordings"

# The HTTP library each vendor SDK is built on.
HTTP_LIBRARY: dict[str, Any] = {
    "anthropic": httpx2,
    "google": httpx,
    "openai": httpx2,
    "mistral": httpx2,
    "perplexity": httpx,
}


def recording_path(config_id: str, role: str) -> Path:
    return RECORDINGS / f"{config_id}.{role}.json"


def load_input() -> dict[str, Any]:
    document: dict[str, Any] = json.loads((RECORDINGS / "_input.json").read_text(encoding="utf-8"))
    return document


def render_sources(sources: list[dict[str, str]]) -> str:
    """The delimited data part of a structuring request (test format, not a product prompt)."""
    return "\n".join(
        f'<source id="{source["source_id"]}">{source["text"]}</source>' for source in sources
    )


def adapter_for(config: ProviderConfigSpec, role: Role, http_client: Any, key: str) -> Any:
    module: ModuleType = import_module(f"app.providers.adapters.{config.provider}_adapter")
    factory = getattr(ADAPTERS[(config.provider, config.api)], role)
    original = module.make_client
    with patch.object(
        module, "make_client", lambda cfg, api_key: original(cfg, api_key, http_client)
    ):
        return factory(config, key)
