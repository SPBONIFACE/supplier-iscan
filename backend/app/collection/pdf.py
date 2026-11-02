"""Text and author of a PDF. PDFs are hostile input: any pypdf failure, an encrypted file or a
file without text is an empty result (logged by the caller as "empty content"), never a crash.
Callers enforce the byte cap while downloading; the page cap is applied here.
"""

import io
import logging
import time
import unicodedata
from dataclasses import dataclass

from pypdf import PdfReader

logger = logging.getLogger(__name__)
MAX_SECONDS = 30.0  # time limit across pages (pypdf has no timeout of its own)


@dataclass
class PdfContent:
    text: str
    author: str | None = None


def extract_pdf(content: bytes, max_pages: int, max_seconds: float = MAX_SECONDS) -> PdfContent:
    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            logger.info("PDF is encrypted: no text extracted")
            return PdfContent("")
        author = None
        try:
            author = (
                " ".join((reader.metadata.author or "").split()) or None
                if reader.metadata
                else None
            )
        except Exception:  # metadata is optional and hostile
            logger.info("PDF metadata unreadable", exc_info=True)
        deadline = time.monotonic() + max_seconds
        parts: list[str] = []
        for page in reader.pages[:max_pages]:
            if time.monotonic() > deadline:
                logger.warning("PDF text extraction stopped at the time limit")
                break
            parts.append(page.extract_text() or "")
        text = unicodedata.normalize("NFC", "\n".join(parts)).strip()
        return PdfContent(text, author)
    except Exception:  # pypdf raises many kinds of errors on malformed files
        logger.warning("PDF could not be read", exc_info=True)
        return PdfContent("")
