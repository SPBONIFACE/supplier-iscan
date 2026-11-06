"""Smoke test of the name-detection model inside the built backend image (#52).

Run INSIDE the container, offline, with the application on the path:

    docker run --network none --memory 4g -e PYTHONPATH=/app -v "$PWD/deploy:/smoke:ro" IMAGE \
        /opt/venv/bin/python /smoke/smoke_redaction.py

It loads the model, redacts short texts that hold personal names and checks that the names are gone
and the rest stays. It prints the load time, the time of the first and of a later call and the peak
memory of the process, as one JSON line (the last line) for the pipeline to report.
Exit code 0: the model runs and works; anything else: it does not.
"""

import json
import os
import resource
import sys
import time
from pathlib import Path

from app.redaction import OMISSION, Redactor
from app.redaction.engine import get_redactor

CASES = [
    ("Kind regards,\nHollis Varney\nSales Office", "Varney", "Sales Office"),
    ("Contact: JEAN DUPONT, Purchasing Director", "DUPONT", "Purchasing Director"),
    ("Mit freundlichen Grüßen\nDietmar Kaltenbach\nVertrieb", "Kaltenbach", "Vertrieb"),
]
PARAGRAPH = (
    "Acme Components supplies fasteners and has been certified since 2011. "
    "For quotes, write to Anna Meyer in the sales office. "
)


def cgroup_peak_mb() -> float | None:
    """Peak memory of the whole container, when the runtime exposes it (cgroup v2)."""
    for path in ("/sys/fs/cgroup/memory.peak", "/sys/fs/cgroup/memory/memory.max_usage_in_bytes"):
        try:
            return int(Path(path).read_text().strip()) / 1_000_000
        except (OSError, ValueError):
            continue
    return None


def main() -> int:
    for name, value in (("HF_HUB_OFFLINE", "1"), ("TRANSFORMERS_OFFLINE", "1")):
        if os.environ.get(name) != value:
            print(f"FAIL: {name} must be {value} in the image", file=sys.stderr)
            return 1
    redactor: Redactor = get_redactor()
    started = time.monotonic()
    redactor.load()
    load_seconds = time.monotonic() - started

    first_seconds = None
    for text, gone, kept in CASES:
        began = time.monotonic()
        out = redactor.redact(text).text
        first_seconds = first_seconds or time.monotonic() - began
        if gone in out or kept not in out or OMISSION not in out:
            print("FAIL: a name was not removed, or the text around it was lost", file=sys.stderr)
            return 1

    long_text = PARAGRAPH * 100  # about 12 kB
    began = time.monotonic()
    out = redactor.redact(long_text).text
    long_seconds = time.monotonic() - began
    if "Meyer" in out:
        print("FAIL: a name in a long text was not removed", file=sys.stderr)
        return 1

    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1000  # kilobytes on Linux
    result = {
        "model_load_seconds": round(load_seconds, 1),
        "first_redaction_seconds": round(first_seconds or 0.0, 2),
        "long_text_chars": len(long_text),
        "long_text_seconds": round(long_seconds, 1),
        "process_peak_mb": round(peak_mb),
        "container_peak_mb": round(cgroup_peak_mb() or 0) or None,
    }
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
