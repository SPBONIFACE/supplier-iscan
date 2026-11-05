"""The disclaimer printed on every page of the PDF (#39).

It is regulatory text supplied by the owner from reviewed sources, never written here: it is read
from a content file (`PDF_DISCLAIMER_FILE`, the shipped placeholder when unset), so that changing
it needs no code change and no template edit.
"""

import json
from functools import lru_cache
from pathlib import Path

from app.config import Settings
from app.pdf.strings import LANGS, Lang

EXAMPLE_FILE = Path(__file__).resolve().parent.parent / "content" / "pdf-disclaimer.example.json"
MAX_LENGTH = 2000


class DisclaimerError(ValueError):
    """The disclaimer file is unreadable or lacks a language (the message never shows its text)."""


@lru_cache(maxsize=8)
def _load(path: str) -> dict[str, str]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise DisclaimerError("The PDF disclaimer file cannot be read.") from error
    texts: dict[str, str] = {}
    for lang in LANGS:
        value = data.get(lang) if isinstance(data, dict) else None
        if not isinstance(value, str) or not value.strip() or len(value) > MAX_LENGTH:
            raise DisclaimerError(f"The PDF disclaimer file has no valid text for {lang}.")
        texts[lang] = value.strip()
    return texts


def disclaimer_text(settings: Settings, lang: Lang) -> str:
    path = settings.pdf_disclaimer_file or str(EXAMPLE_FILE)
    return _load(path)[lang]
