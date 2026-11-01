"""The adapter of every (provider, api) pair that `catalogue.PROVIDER_APIS` lists, per role."""

from app.providers.adapters import (
    anthropic_adapter,
    google_adapter,
    mistral_adapter,
    openai_adapter,
    perplexity_adapter,
)
from app.providers.catalogue import ProviderName
from app.providers.registry import AdapterFactories

ADAPTERS: dict[tuple[ProviderName, str], AdapterFactories] = {
    ("anthropic", "messages"): AdapterFactories(
        structuring=anthropic_adapter.build_structuring, retrieval=anthropic_adapter.build_retrieval
    ),
    ("google", "generate_content"): AdapterFactories(
        structuring=google_adapter.build_structuring, retrieval=google_adapter.build_retrieval
    ),
    ("openai", "responses"): AdapterFactories(
        structuring=openai_adapter.build_structuring, retrieval=openai_adapter.build_retrieval
    ),
    ("mistral", "chat_completions"): AdapterFactories(
        structuring=mistral_adapter.build_structuring
    ),
    ("mistral", "conversations"): AdapterFactories(retrieval=mistral_adapter.build_retrieval),
    ("perplexity", "chat_completions"): AdapterFactories(
        structuring=perplexity_adapter.build_structuring,
        retrieval=perplexity_adapter.build_retrieval,
    ),
}
