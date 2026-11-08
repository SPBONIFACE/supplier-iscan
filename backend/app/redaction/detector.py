"""Person-name detectors for redaction (#19): GLiNER for all scripts, spaCy `zh` for Han text.

`NameDetector.person_spans(texts)` returns, for each text, the spans a model takes for a person.
Everything around it (rules, extension over name tokens, company words, fail-closed) is in
`engine.py`; this module only runs models.

Model handling (owner decisions D-066, D-068):
- the model is a directory made by `scripts/fetch_model.py` (pinned revision, sha256-checked at
  build time); nothing is ever downloaded at run time: HF_HUB_OFFLINE and TRANSFORMERS_OFFLINE are
  forced to 1 here before any library reads them;
- the checkpoint is a pickle: `torch.load` is forced to `weights_only=True` while it loads, and a
  load that asks for anything else fails; `trust_remote_code` is never set;
- any problem (missing file, bad checkpoint, error in a chunk) raises: the caller fails closed.

Long text is cut into chunks that overlap, so that a name on a boundary lies whole in one chunk.
"""

import logging
import os
import re
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final, Protocol, cast

from app.redaction.text import RedactionUnavailable

logger = logging.getLogger(__name__)

Span = tuple[int, int]

MODEL_DIR_ENV: Final = "REDACTION_MODEL_DIR"
THRESHOLD_ENV: Final = "REDACTION_GLINER_THRESHOLD"
THREADS_ENV: Final = "REDACTION_THREADS"
DEFAULT_THRESHOLD: Final = 0.9
DEFAULT_THREADS: Final = 4
MODEL_REVISION: Final = "1fcf13e85f4eef5394e1fcd406cf2ca9ea82351d"
LABEL: Final = "person"

# Characters per chunk, overlap, and the cap on GLiNER words per chunk (the model reads 384 words
# and silently drops the rest: a chunk may never come near it). Han text is cut shorter.
CHUNK_CHARS: Final = 1_200
CHUNK_OVERLAP: Final = 200
HAN_CHUNK_CHARS: Final = 400
HAN_CHUNK_OVERLAP: Final = 100
MAX_CHUNK_WORDS: Final = 300
BATCH_SIZE: Final = 16
SPACY_CHUNK_CHARS: Final = 20_000
SPACY_OVERLAP: Final = 200

_HAN: Final = re.compile(r"[㐀-鿿豈-﫿]")
_GLINER_WORD: Final = re.compile(r"\w+(?:[-_]\w+)*|\S")


class NameDetector(Protocol):
    def person_spans(self, texts: Sequence[str]) -> list[list[Span]]: ...


def has_han(text: str) -> bool:
    return _HAN.search(text) is not None


def chunk_text(
    text: str,
    limit: int = CHUNK_CHARS,
    overlap: int = CHUNK_OVERLAP,
    max_words: int | None = None,
) -> list[tuple[int, str]]:
    """Pieces `(offset, piece)` of at most `limit` characters (and `max_words` GLiNER words) that
    overlap by about `overlap` characters. Cuts fall on a line break or a space when there is one.
    Every position of the text lies in at least one piece, and a run of up to `overlap` characters
    lies whole in at least one piece."""
    if len(text) <= limit and (max_words is None or _word_count(text) <= max_words):
        return [(0, text)]
    pieces: list[tuple[int, str]] = []
    position, size = 0, len(text)
    while position < size:
        end = min(size, position + limit)
        if max_words is not None:
            end = _within_words(text, position, end, max_words)
        if end < size:
            end = _cut(text, position, end)
        pieces.append((position, text[position:end]))
        if end >= size:
            break
        position = _restart(text, position, end, overlap)
    return pieces


def _word_count(text: str) -> int:
    return sum(1 for _ in _GLINER_WORD.finditer(text))


def _within_words(text: str, start: int, end: int, max_words: int) -> int:
    count = 0
    for match in _GLINER_WORD.finditer(text, start, end):
        count += 1
        if count > max_words:
            return max(match.start(), start + 1)
    return end


def _cut(text: str, start: int, end: int) -> int:
    """The end of a piece: after the last line break or space in its second half, else `end`."""
    for separator in ("\n", " "):
        cut = text.rfind(separator, start + (end - start) // 2, end)
        if cut != -1:
            return cut + 1
    return end


def _restart(text: str, start: int, end: int, overlap: int) -> int:
    """Where the next piece begins: about `overlap` characters before `end`, at a word start."""
    wanted = max(start + 1, end - overlap)
    for index in range(wanted, end):
        if text[index - 1].isspace():
            return index
    return wanted


@contextmanager
def _pickle_safe_load() -> Iterator[None]:
    """While a model loads, `torch.load` is `weights_only=True` whatever the caller asks."""
    import torch

    original = torch.load

    def strict(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("weights_only") is False:
            raise RedactionUnavailable
        kwargs["weights_only"] = True
        return original(*args, **kwargs)

    torch.load = strict
    try:
        yield
    finally:
        torch.load = original


def model_directory() -> Path:
    configured = os.environ.get(MODEL_DIR_ENV, "").strip()
    if configured:
        return Path(configured)
    return Path.home() / ".cache" / "supplier-iscan" / f"gliner-multi-pii-{MODEL_REVISION[:8]}"


def _env_number(name: str, default: float, parse: Callable[[str], float]) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return parse(raw)
    except ValueError:
        raise RedactionUnavailable from None


class GlinerDetector:
    """GLiNER multi PII, label `person`, on CPU. Load once; calls are serialised."""

    def __init__(
        self,
        directory: Path | None = None,
        threshold: float | None = None,
        threads: int | None = None,
    ) -> None:
        self._directory = directory or model_directory()
        self._threshold = (
            threshold
            if threshold is not None
            else _env_number(THRESHOLD_ENV, DEFAULT_THRESHOLD, float)
        )
        self._threads = int(
            threads if threads is not None else _env_number(THREADS_ENV, DEFAULT_THREADS, int)
        )
        if not 0.0 < self._threshold <= 1.0 or self._threads < 1:
            raise RedactionUnavailable
        self._model: Any = None
        self._lock = threading.Lock()

    def load(self) -> None:
        # Offline before the libraries are imported: they read these variables at import time.
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        if not (self._directory / "pytorch_model.bin").is_file():
            raise RedactionUnavailable
        import torch
        from gliner import GLiNER  # type: ignore[import-untyped]

        torch.set_num_threads(self._threads)
        with _pickle_safe_load():
            self._model = GLiNER.from_pretrained(str(self._directory), local_files_only=True)

    def person_spans(self, texts: Sequence[str]) -> list[list[Span]]:
        if self._model is None:
            raise RedactionUnavailable
        pieces: list[str] = []
        owners: list[tuple[int, int]] = []
        for index, text in enumerate(texts):
            if has_han(text):
                chunks = chunk_text(text, HAN_CHUNK_CHARS, HAN_CHUNK_OVERLAP)
            else:
                chunks = chunk_text(text, max_words=MAX_CHUNK_WORDS)
            for offset, piece in chunks:
                pieces.append(piece)
                owners.append((index, offset))
        found: list[list[Span]] = [[] for _ in texts]
        with self._lock:
            for first in range(0, len(pieces), BATCH_SIZE):
                batch = pieces[first : first + BATCH_SIZE]
                results = self._model.batch_predict_entities(
                    batch, [LABEL], threshold=self._threshold
                )
                for (index, offset), entities in zip(
                    owners[first : first + BATCH_SIZE], results, strict=True
                ):
                    found[index].extend(
                        (offset + entity["start"], offset + entity["end"]) for entity in entities
                    )
        return found


class SpacyHanDetector:
    """spaCy `zh_core_web_sm` (`ner` pipe only), for text with Han characters."""

    PACKAGE: Final = "zh_core_web_sm"
    LABELS: Final = frozenset({"PERSON", "PER"})

    def __init__(self) -> None:
        self._nlp: Any = None
        self._lock = threading.Lock()

    def load(self) -> None:
        import spacy
        from spacy.cli.info import info

        pipeline = cast(dict[str, Any], info(self.PACKAGE, silent=True))["pipeline"]
        self._nlp = spacy.load(self.PACKAGE, exclude=[p for p in pipeline if p != "ner"])
        self._nlp.max_length = SPACY_CHUNK_CHARS * 2

    def person_spans(self, texts: Sequence[str]) -> list[list[Span]]:
        if self._nlp is None:
            raise RedactionUnavailable
        found: list[list[Span]] = []
        for text in texts:
            spans: list[Span] = []
            if has_han(text):
                for offset, piece in chunk_text(text, SPACY_CHUNK_CHARS, SPACY_OVERLAP):
                    if not has_han(piece):
                        continue
                    with self._lock:
                        entities = self._nlp(piece).ents
                    spans.extend(
                        (offset + entity.start_char, offset + entity.end_char)
                        for entity in entities
                        if entity.label_ in self.LABELS
                    )
            found.append(spans)
        return found


def strip_cjk(text: str, span: Span) -> Span | None:
    """Trim blanks and punctuation off a span; None when nothing is left."""
    inside = text[span[0] : span[1]]
    stripped = inside.strip(" \t\n,.;:()")
    if not stripped:
        return None
    start = span[0] + inside.index(stripped)
    return start, start + len(stripped)
