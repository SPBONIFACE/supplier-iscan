"""Extraction settings, read from environment variables (all optional).

- `EXTRACT_MAX_INPUT_CHARS` (20000): the most source text sent to the structuring provider in one
  call. A longer source is cut at a line or word boundary into several calls.
- `EXTRACT_GROUPS_PER_CALL` (0): how many consecutive field groups (sections of the definition)
  one call asks for. 0 = all groups in one call per chunk; 1 = one call per section and chunk;
  n = batches of n groups. Facts are stored per section whatever the value.
- `EXTRACT_CONCURRENCY` (1): how many source-chunk calls to run in parallel per batch, using a
  bounded `ThreadPoolExecutor`. 1 = sequential (default); 2–8 = parallel. Database writes stay on
  the stage thread; results are merged in source order after all futures settle.
- `EXTRACT_MIN_QUOTE_CHARS` (12): the shortest quote kept, in characters after normalisation.
- `EXTRACT_MIN_QUOTE_CHARS_CJK` (4): the same for a quote with Han, Hiragana, Katakana or Hangul.
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
GROUPS_PER_CALL = "EXTRACT_GROUPS_PER_CALL"
CONCURRENCY = "EXTRACT_CONCURRENCY"
MIN_QUOTE_CHARS = "EXTRACT_MIN_QUOTE_CHARS"
MIN_QUOTE_CHARS_CJK = "EXTRACT_MIN_QUOTE_CHARS_CJK"
IAF_CERTSEARCH_URL = "IAF_CERTSEARCH_URL"
DEFAULT_CERTSEARCH_URL = "https://www.iafcertsearch.org/"


@dataclass(frozen=True)
class ExtractionSettings:
    max_input_chars: int = 20_000
    certsearch_url: str = DEFAULT_CERTSEARCH_URL
    min_quote_chars: int = 12
    min_quote_chars_cjk: int = 4
    groups_per_call: int = 0
    extract_concurrency: int = 1


def _whole_number(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    if not (raw.isascii() and raw.isdigit()) or not 1 <= int(raw) <= 300:
        raise ConfigurationError(f"{name} must be a whole number between 1 and 300")
    return int(raw)


def _concurrency(env: Mapping[str, str]) -> int:
    raw = env.get(CONCURRENCY, "").strip()
    if not raw:
        return 1
    if not (raw.isascii() and raw.isdigit()) or not 1 <= int(raw) <= 8:
        raise ConfigurationError(f"{CONCURRENCY} must be a whole number between 1 and 8")
    return int(raw)


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
    raw = env.get(GROUPS_PER_CALL, "").strip()
    per_call = defaults.groups_per_call
    if raw:
        if not (raw.isascii() and raw.isdigit()) or int(raw) > 100:
            raise ConfigurationError(f"{GROUPS_PER_CALL} must be a whole number between 0 and 100")
        per_call = int(raw)
    url = env.get(IAF_CERTSEARCH_URL, "").strip() or defaults.certsearch_url
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username:
        raise ConfigurationError(f"{IAF_CERTSEARCH_URL} must be an http(s) address")
    return ExtractionSettings(
        max_input_chars=size,
        certsearch_url=url,
        groups_per_call=per_call,
        extract_concurrency=_concurrency(env),
        min_quote_chars=_whole_number(env, MIN_QUOTE_CHARS, defaults.min_quote_chars),
        min_quote_chars_cjk=_whole_number(env, MIN_QUOTE_CHARS_CJK, defaults.min_quote_chars_cjk),
    )
