"""Measure and check the detector work of redaction (#196), with the real model.

    uv run python -m tests.redaction.measure_perf [--steps a,b,c|none|all] [--check]
    uv run python -m tests.redaction.measure_perf --write-expected      (on `main` only)

Prints, per corpus item, the model calls (pieces sent to GLiNER), the seconds and the peak memory.
`--steps` switches the steps of `app.redaction.detector` (a: run cache, b: skip non-text pieces,
c: one call for identical pieces); `--check` compares every output with `perf_expected.json`.
"""

import hashlib
import json
import resource
import sys
import time
import uuid
from contextlib import nullcontext
from pathlib import Path

from app.redaction import detector, get_redactor
from tests.redaction.perf_corpus import corpus

EXPECTED = Path(__file__).parent / "perf_expected.json"
SMALL = {"site", "table", "short"}


def set_steps(steps: str) -> None:
    chosen = {"a", "b", "c"} if steps == "all" else set() if steps == "none" else set(steps)
    detector.CACHE_PIECES = "a" in chosen
    detector.SKIP_NON_TEXT = "b" in chosen
    detector.DEDUPE_CALL = "c" in chosen


def fingerprint(texts: list[str]) -> dict[str, object]:
    joined = "\x00".join(texts)
    return {"chars": len(joined), "sha256": hashlib.sha256(joined.encode()).hexdigest()}


def run(steps: str) -> dict[str, tuple[list[str], int, float]]:
    set_steps(steps)
    redactor = get_redactor()
    redactor.load()
    calls = [0]
    model = redactor._detector._model  # type: ignore[union-attr]
    original = model.batch_predict_entities

    def counting(batch, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls[0] += len(batch)
        return original(batch, *args, **kwargs)

    model.batch_predict_entities = counting
    out: dict[str, tuple[list[str], int, float]] = {}
    for name, texts in corpus().items():
        calls[0] = 0
        started = time.monotonic()
        scope = getattr(detector, "run_piece_cache", None)  # absent on `main`
        with scope(uuid.uuid4()) if scope else nullcontext():
            redacted = [redactor.redact(text).text for text in texts]
        out[name] = (redacted, calls[0], time.monotonic() - started)
    return out


def main() -> int:
    args = sys.argv[1:]
    steps = args[args.index("--steps") + 1] if "--steps" in args else "all"
    results = run("none" if "--write-expected" in args else steps)
    if "--write-expected" in args:
        data = {
            name: ({"texts": r[0]} if name in SMALL else fingerprint(r[0]))
            for name, r in results.items()
        }
        EXPECTED.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print("written", EXPECTED)
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    print(f"steps={steps}")
    bad = 0
    for name, (texts, calls, seconds) in results.items():
        want = expected[name]
        same = texts == want["texts"] if name in SMALL else fingerprint(texts) == want
        bad += not same
        print(f"{name:10} calls={calls:5} seconds={seconds:7.1f} identical={same}")
    print(f"peak_rss_gb={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**30:.2f}")
    return 1 if bad and "--check" in args else 0


if __name__ == "__main__":
    raise SystemExit(main())
