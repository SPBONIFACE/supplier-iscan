"""Measure the name detector on the synthetic evaluation set (`evalset/`), with the real model.

    uv run python -m tests.redaction.measure_detector [--timing]

Prints, for the report part (ids with `id % 10 >= 3`) of the main set and for the fresh set: names
hidden by language and style, the worst language per style, plain lists, Chinese, ordinary lines
altered, and name + title lines kept. A name counts as hidden when every letter and digit of its
span lies inside a removed span. `--timing` adds the time for 100 kB of text, plain and in capitals,
and the peak memory of the process. Needs the model (`make fetch-model`).
"""

import json
import resource
import sys
import time
from collections import defaultdict
from pathlib import Path

from app.redaction import get_redactor

SET = Path(__file__).parent / "evalset"
LATIN = ("en", "fr", "de", "es", "it")
Span = tuple[int, int]


def load(folder: str, name: str) -> list[dict]:  # type: ignore[type-arg]
    path = SET / folder / f"{name}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def covered(text: str, start: int, end: int, removed: list[Span]) -> bool:
    return all(any(a <= k < b for a, b in removed) for k in range(start, end) if text[k].isalnum())


def touched(text: str, start: int, end: int, removed: list[Span]) -> bool:
    return any(text[k].isalnum() and any(a <= k < b for a, b in removed) for k in range(start, end))


def pct(counter: list[int]) -> str:
    return f"{100 * counter[0] / counter[1]:.0f}" if counter[1] else "-"


def report(label: str, folder: str, report_part: bool) -> None:
    redactor = get_redactor()

    def keep(item: dict) -> bool:  # type: ignore[type-arg]
        return not report_part or item["id"] % 10 >= 3

    cells: dict[object, list[int]] = defaultdict(lambda: [0, 0])
    for item in filter(keep, load(folder, "names")):
        removed = redactor.removed_spans(item["text"])
        for start, end in item["spans"]:
            ok = covered(item["text"], start, end, removed)
            for key in ("all", (item["lang"], item["style"]), (item["lang"], item["ctx"])):
                cells[key][0] += ok
                cells[key][1] += 1
    ordinary = [i for i in load(folder, "ordinary") if keep(i)]
    altered = [i for i in ordinary if redactor.removed_spans(i["text"])]
    print(f"== {label}: {cells['all'][1]} names, {len(ordinary)} ordinary lines")
    print("names hidden, all:", pct(cells["all"]))
    for style in ("normal", "all_caps", "lower"):
        worst = min(
            LATIN, key=lambda lang: cells[(lang, style)][0] / (cells[(lang, style)][1] or 1)
        )
        cell = cells[(worst, style)]
        row = " ".join(f"{lang}={pct(cells[(lang, style)])}" for lang in LATIN)
        print(f"  {style}: lowest {pct(cell)} ({worst}); {row}")
    if folder == "main":
        worst_list = min(
            LATIN, key=lambda lang: cells[(lang, "list")][0] / cells[(lang, "list")][1]
        )
        print(f"  plain list: lowest {pct(cells[(worst_list, 'list')])} ({worst_list})")
        print(f"  Chinese (zh, normal): {pct(cells[('zh', 'normal')])}")
    print(
        f"ordinary lines altered: {len(altered)}/{len(ordinary)} = "
        f"{100 * len(altered) / max(1, len(ordinary)):.1f}%"
    )
    for item in altered:
        spans = redactor.removed_spans(item["text"])
        print(
            "   ",
            item["lang"],
            item["text"][:50].replace("\n", "/"),
            "->",
            ["".join(item["text"][a:b]) for a, b in spans],
        )
    titles = [i for i in load(folder, "titles") if keep(i)]
    if titles:
        good = 0
        for item in titles:
            removed = redactor.removed_spans(item["text"])
            good += covered(
                item["text"], item["name_span"][0], item["name_span"][1], removed
            ) and not touched(item["text"], item["title_span"][0], item["title_span"][1], removed)
        print(f"name hidden and title kept: {good} of {len(titles)}")


def timing() -> None:
    redactor = get_redactor()
    lines = [i["text"] for i in load("main", "ordinary")]
    prose = [
        i["text"] for i in load("main", "names") if i["ctx"] == "prose" and i["style"] == "normal"
    ]
    document: list[str] = []
    index = 0
    while sum(len(line) + 1 for line in document) < 100_000:
        document.append(lines[index % len(lines)])
        if index % 5 == 0:
            document.append(prose[(index // 5) % len(prose)])
        index += 1
    plain = "\n".join(document)[:100_000]
    for tag, text in (("plain", plain), ("capitals", plain.upper())):
        started = time.perf_counter()
        redactor.removed_spans(text)
        print(f"100 kB {tag}: {time.perf_counter() - started:.0f} s")
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(f"peak memory: {peak / (1 << 30 if sys.platform == 'darwin' else 1 << 20):.2f} GB")


def main() -> None:
    started = time.perf_counter()
    get_redactor().load()
    print(f"model load: {time.perf_counter() - started:.0f} s")
    report("main set, report part", "main", True)
    report("fresh set", "fresh", False)
    if "--timing" in sys.argv:
        timing()


if __name__ == "__main__":
    main()
