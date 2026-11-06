"""`make provider-shape CONFIG=<id>`: one retrieval call on a synthetic public query, with the shape
diagnostic on (#122). It writes the SHAPE of the response (names and types, no text, no URL) to
`diagnostics/` (git-ignored), which can be shared.

The configuration is looked up in the approved list like a live `make eval`; its key is read from
the environment by name; the query goes through the redaction gate and the metered retrieval
client, so the call is exactly the one a run makes. Nothing about the response is printed.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from app.config import ConfigurationError, load_settings
from app.providers import ProviderError, Providers, load_catalogue
from app.providers.interface import RetrievalRequest
from app.providers.metering import CallContext, ListSink, UsageMeter
from app.providers.pricing import check_prices, load_price_table
from app.providers.shape import FLAG
from app.redaction import RedactionGate
from app.redaction.text import RedactionUnavailable
from eval.areas import ORGANISATION

# A public company and a generic instruction: no personal data, nothing of the owner's.
QUERY = "Siemens AG, Munich, Germany: official website and annual report"
INSTRUCTIONS = "Find public web pages that describe the company below."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="provider-shape", description=__doc__)
    parser.add_argument("--config", required=True, help="approved retrieval configuration id")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    os.environ[FLAG] = "1"
    try:
        settings = load_settings()
        catalogue = load_catalogue(
            Path(settings.provider_config_file) if settings.provider_config_file else None
        )
        prices = load_price_table(
            Path(settings.price_table_file) if settings.price_table_file else None
        )
        check_prices(catalogue, prices, settings.eur_per_usd)
        meter = UsageMeter(prices, settings.eur_per_usd, ListSink())
        client = Providers(catalogue, os.environ, meter=meter).retrieval(args.config)
        query = RedactionGate(lambda: ()).redact(QUERY)
    except (ConfigurationError, ProviderError, RedactionUnavailable) as error:
        print(f"provider-shape: {error}", file=sys.stderr)
        return 2
    try:
        result = client.retrieve(
            RetrievalRequest(INSTRUCTIONS, query), CallContext(organisation_id=ORGANISATION)
        )
    except ProviderError as error:
        print(f"provider-shape: the call failed ({error})", file=sys.stderr)
        return 1
    print(f"provider-shape: the adapter read {len(result.urls)} address(es) from the response")
    return 0


if __name__ == "__main__":
    sys.exit(main())
