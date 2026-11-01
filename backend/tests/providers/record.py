"""Re-record the contract fixtures against the live provider APIs.

    cd backend
    GEMINI_API_KEY=... uv run python -m tests.providers.record --config gemini-flash-structuring

The keys are read from the environment by name (KEY_SETTINGS), as in the application; the command
sets nothing and writes no key. It records only approved configurations, so the configuration
file is the operator's own (PROVIDER_CONFIG_FILE, with the point checks done); the shipped example
is disabled. The input is always the synthetic one of `recordings/_input.json`: a fictitious
supplier for structuring, a public listed company for retrieval. Each recording keeps the last
HTTP exchange, so the file holds exactly what the provider answered; the command refuses to write a
file that contains the key or an email address. Review the diff before committing.
"""

import argparse
import json
import os
import re
import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.config import PROVIDER_CONFIG_FILE, ConfigurationError, load_settings
from app.providers.catalogue import ROLES, ProviderConfigSpec, Role, load_catalogue
from app.providers.interface import (
    RetrievalClient,
    RetrievalRequest,
    StructuringClient,
    StructuringRequest,
)
from app.providers.metering import CallContext, ListSink, UsageEntry, UsageMeter
from app.providers.pricing import PriceTable, load_price_table
from tests.providers.replay import (
    HTTP_LIBRARY,
    RECORDINGS,
    adapter_for,
    load_input,
    recording_path,
    render_sources,
)

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
CONTEXT = CallContext(organisation_id=uuid.UUID(int=0))

TransportFactory = Callable[[Any], Any]  # the HTTP library -> the transport that does the call


def recording_http_client(
    library: Any, captured: list[tuple[int, Any]], inner: TransportFactory
) -> Any:
    transport = inner(library)

    class RecordingTransport(library.BaseTransport):  # type: ignore[misc]
        def handle_request(self, request: Any) -> Any:
            response = transport.handle_request(request)
            response.read()
            captured.append((response.status_code, json.loads(response.content)))
            return response

    return library.Client(transport=RecordingTransport())


def _usage_fields(entry: UsageEntry) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "input_tokens": entry.input_tokens,
        "output_tokens": entry.output_tokens,
        "reasoning_tokens": entry.reasoning_tokens,
        "tool_calls": entry.tool_calls,
    }
    if entry.cost_basis == "provider":
        fields["billed_amount"] = str(entry.billed_amount.normalize())
        fields["billed_currency"] = entry.billed_currency
    return fields


def record(
    config: ProviderConfigSpec,
    role: Role,
    key: str,
    inner: TransportFactory | None = None,
    prices: PriceTable | None = None,
    directory: Path = RECORDINGS,
) -> Path:
    """Call the provider once through the real adapter and write the recording."""
    library = HTTP_LIBRARY[config.provider]
    captured: list[tuple[int, Any]] = []
    http_client = recording_http_client(
        library, captured, inner or (lambda lib: lib.HTTPTransport())
    )
    adapter = adapter_for(config, role, http_client, key)
    sink = ListSink()
    meter = UsageMeter(prices or load_price_table(), Decimal(1), sink)
    material = load_input()
    document: dict[str, Any] = {
        "$comment": "Recorded with `python -m tests.providers.record` (tests/providers/README.md).",
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "origin": "recorded from the live API",
        "config_id": config.id,
        "role": role,
    }
    if role == "structuring":
        from app.llm_schemas import FieldExtractionBatch

        request = StructuringRequest(
            instructions=material["instructions"], data=render_sources(material["sources"])
        )
        StructuringClient(config, adapter, meter).structure(request, FieldExtractionBatch, CONTEXT)
    else:
        result = RetrievalClient(config, adapter, meter).retrieve(
            RetrievalRequest(
                instructions=material["retrieval_instructions"], query=material["query"]
            ),
            CONTEXT,
        )
        document["expected_urls"] = [item.url for item in result.urls]
    status, body = captured[-1]
    document.update(status=status, body=body, expected_usage=_usage_fields(sink.entries[-1]))
    text = json.dumps(document, indent=2, ensure_ascii=False)
    if key in text:
        raise SystemExit("Refused: the recording contains the API key.")
    if EMAIL.search(text):
        raise SystemExit("Refused: the recording contains an email address; check it by hand.")
    path = directory / recording_path(config.id, role).name
    path.write_text(text + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    parser.add_argument("--config", required=True, help="id of an approved configuration")
    parser.add_argument("--role", choices=ROLES, help="only this role (default: all it supports)")
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
        config_file, price_file = settings.provider_config_file, settings.price_table_file
        catalogue = load_catalogue(Path(config_file) if config_file else None)
        prices = load_price_table(Path(price_file) if price_file else None)
    except ConfigurationError as error:
        print(error, file=sys.stderr)
        return 2
    config = catalogue.by_id.get(args.config)
    if config is None:
        print(f"Unknown configuration {args.config!r}.", file=sys.stderr)
        return 2
    if not config.approved:
        print(
            f"Configuration {config.id!r} is not approved (enabled and verified): set it in your "
            f"own file named by {PROVIDER_CONFIG_FILE}.",
            file=sys.stderr,
        )
        return 2
    key = os.environ.get(config.key_setting, "").strip()
    if not key:
        print(f"The setting {config.key_setting} is not set.", file=sys.stderr)
        return 2
    for role in ROLES:
        if role in config.roles and args.role in (None, role):
            print(f"Recorded {record(config, role, key, prices=prices)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
