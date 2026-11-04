"""Extraction settings, read from environment variables (all optional).

- `EXTRACT_MAX_INPUT_CHARS` (20000): the most source text sent to the structuring provider in one
  call. A longer source is cut at a line or word boundary into several calls.
- `IAF_CERTSEARCH_URL` (https://www.iafcertsearch.org/): where a buyer verifies a certificate; the
  "Verify on IAF CertSearch" link of a certification fact. A configuration value, not a product
  term: an operator can point it elsewhere.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.config import ConfigurationError

MAX_INPUT_CHARS = "EXTRACT_MAX_INPUT_CHARS"
IAF_CERTSEARCH_URL = "IAF_CERTSEARCH_URL"
DEFAULT_CERTSEARCH_URL = "https://www.iafcertsearch.org/"


@dataclass(frozen=True)
class ExtractionSettings:
    max_input_chars: int = 20_000
    certsearch_url: str = DEFAULT_CERTSEARCH_URL


def load_extraction_settings(environ: Mapping[str, str] | None = None) -> ExtractionSettings:
    env = os.environ if environ is None else environ
    defaults = ExtractionSettings()
    raw = env.get(MAX_INPUT_CHARS, "").strip()
    size = defaults.max_input_chars
    if raw:
        if not (raw.isascii() and raw.isdigit()) or not 500 <= int(raw) <= 1_000_000:
            raise ConfigurationError(
                f"{MAX_INPUT_CHARS} must be a whole number between 500 and 1000000"
            )
        size = int(raw)
    url = env.get(IAF_CERTSEARCH_URL, "").strip() or defaults.certsearch_url
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username:
        raise ConfigurationError(f"{IAF_CERTSEARCH_URL} must be an http(s) address")
    return ExtractionSettings(max_input_chars=size, certsearch_url=url)
