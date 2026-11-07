"""`make provider-check CONFIG=<id>`: one tiny synthetic structured call (#125).

It prints OK, or the failure with the provider's error type and message (the log line of the
failed call), and nothing else: no prompt, no answer. The call goes through the same approved
configuration, redaction gate and metered structuring client as a run, with a schema that uses the
constraints the app's schemas use (`max_length`), so it also checks the adapter's schema conversion.
The key is read from the environment by name and never printed or taken on the command line.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.config import ConfigurationError, load_settings
from app.providers import ProviderError, Providers, load_catalogue
from app.providers.interface import StructuringRequest
from app.providers.metering import CallContext, ListSink, UsageMeter
from app.providers.pricing import check_prices, load_price_table
from app.redaction import RedactionGate
from app.redaction.text import RedactionUnavailable
from eval.areas import ORGANISATION

INSTRUCTIONS = "Answer with the capital city of the country named in the data."
DATA = "<data>France</data>"


class Ping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capital: str = Field(min_length=1, max_length=100)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="provider-check", description=__doc__)
    parser.add_argument("--config", required=True, help="approved structuring configuration id")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="provider-check: %(message)s")
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
        client = Providers(catalogue, os.environ, meter=meter).structuring(args.config)
        data = RedactionGate(lambda: ()).redact(DATA)
    except (ConfigurationError, ProviderError, RedactionUnavailable) as error:
        print(f"provider-check: {error}", file=sys.stderr)
        return 2
    try:
        context = CallContext(organisation_id=ORGANISATION)
        client.structure(StructuringRequest(INSTRUCTIONS, data), Ping, context)
    except ProviderError as error:
        # The log line above already carries the provider's error type and message.
        print(f"provider-check: FAILED ({error})", file=sys.stderr)
        return 1
    print("provider-check: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
