"""Measure the name detector on the synthetic evaluation set (`evalset/`), with the real model.

    uv run python -m tests.redaction.measure_detector [--timing | --only-timing] [--zh tune|report]

Prints, for the report part (ids with `id % 10 >= 3`) of the main set and for the fresh set: names
hidden by language and style, the worst language per style, plain lists, Chinese, ordinary lines
altered, and name + title lines kept. A name counts as hidden when every letter and digit of its
span lies inside a removed span. `--timing` adds the time for 100 kB of text, plain and in capitals,
and the peak memory of the process; it also times 100,000 characters of Han text.

`--zh tune|report` adds the Chinese set of #100 (`evalset/zh/`): Han and romanised names hidden, by
context and by name type, titles kept, and the companies, places and product words altered. The
tuning part prints the failing cases; the report part prints figures only (it is run once, at the
end, and never used to choose a rule). Needs the model (`make fetch-model`).
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
    languages = sorted({key[0] for key in cells if isinstance(key, tuple)})
    for lang in languages:
        styles = sorted({k[1] for k in cells if isinstance(k, tuple) and k[0] == lang})
        print(f"  {lang}: " + " ".join(f"{s}={pct(cells[(lang, s)])}" for s in styles))
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
    chinese = [i for i in ordinary if i["lang"] == "zh"]
    if chinese:
        print(
            f"  Chinese ordinary lines altered: "
            f"{sum(1 for i in chinese if i in altered)}/{len(chinese)}"
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


def table(title: str, cells: dict[str, list[int]], prefix: str, labels: list[str]) -> None:
    row = "  ".join(
        f"{label}={pct(cells[prefix + label])} ({cells[prefix + label][1]})"
        for label in labels
        if cells[prefix + label][1]
    )
    print(f"  {title}: {row}")


def report_zh(part: str) -> None:
    """The Chinese set of #100: names hidden by script, context and type; titles; other items."""
    redactor = get_redactor()
    report_part = part == "report"

    def keep(item: dict) -> bool:  # type: ignore[type-arg]
        return bool((item["id"] % 10 >= 3) == report_part)

    names = [i for i in load("zh", "names") if keep(i)]
    cells: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    kept_title: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    misses: list[str] = []
    for item in names:
        text = item["text"]
        removed = redactor.removed_spans(text)
        for (start, end), script in zip(item["spans"], item["scripts"], strict=True):
            ok = covered(text, start, end, removed)
            for key in (script, f"{script}/ctx/{item['ctx']}", f"{script}/type/{item['ntype']}"):
                cells[key][0] += ok
                cells[key][1] += 1
            if not ok:
                shown = [text[a:b] for a, b in removed]
                misses.append(f"{item['ntype']:5} {item['ctx']:9} {text!r} -> {shown}")
        for _ in item["title_spans"]:
            name_ok = all(covered(text, a, b, removed) for (a, b) in item["spans"])
            kept = not any(touched(text, a, b, removed) for a, b in item["title_spans"])
            kept_title[item["script"]][0] += name_ok and kept
            kept_title[item["script"]][1] += 1
    count = sum(len(i["spans"]) for i in names)
    print(f"== Chinese set, {part} part: {len(names)} texts, {count} names")
    for script in ("han", "latin"):
        print(f"{script} names hidden, all: {pct(cells[script])} ({cells[script][1]})")
        contexts = sorted({i["ctx"] for i in names if i["script"] == script} | {"dual"})
        types = sorted({i["ntype"] for i in names if i["script"] == script} | {"dual"})
        table("by context", cells, f"{script}/ctx/", contexts)
        table("by type", cells, f"{script}/type/", types)
        print(f"  name hidden and title kept: {pct(kept_title[script])} ({kept_title[script][1]})")
    if not report_part:
        for line in misses:
            print("   MISS", line)
    altered: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    changed: list[str] = []
    for item in (i for i in load("zh", "nonperson") if keep(i)):
        text = item["text"]
        removed = redactor.removed_spans(text)
        for start, end in item["items"]:
            hit = touched(text, start, end, removed)
            keys = ["all", item["kind"], *(["suzhou"] if item["suzhou"] else [])]
            for key in keys:
                altered[key][0] += hit
                altered[key][1] += 1
            if hit:
                shown = [text[a:b] for a, b in removed]
                changed.append(f"{item['kind']:15} {text!r} -> {shown}")
    total = altered["all"]
    detail = "  ".join(f"{k}={v[0]}/{v[1]}" for k, v in altered.items() if k != "all")
    print(
        f"non-person items altered: {total[0]}/{total[1]} = "
        f"{100 * total[0] / max(1, total[1]):.1f}%  {detail}"
    )
    if not report_part:
        for line in changed:
            print("   ALTERED", line)


def han_document() -> str:
    """100,000 characters of Han text: Chinese ordinary lines and sentences with names."""
    lines = [i["text"] for i in load("main", "ordinary") if i["lang"] == "zh"]
    lines += [
        i["text"] for i in load("zh", "names") if i["script"] == "han" and i["ctx"] == "prose"
    ]
    lines += [i["text"] for i in load("zh", "nonperson") if i["kind"] == "company_han"]
    document: list[str] = []
    index = 0
    while sum(len(line) + 1 for line in document) < 100_000:
        document.append(lines[index % len(lines)])
        index += 1
    return "\n".join(document)[:100_000]


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
    started = time.perf_counter()
    redactor.removed_spans(han_document())
    print(f"100,000 characters Han: {time.perf_counter() - started:.0f} s")
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(f"peak memory: {peak / (1 << 30 if sys.platform == 'darwin' else 1 << 20):.2f} GB")


def main() -> None:
    started = time.perf_counter()
    get_redactor().load()
    print(f"model load: {time.perf_counter() - started:.0f} s")
    if "--only-timing" in sys.argv:
        timing()
        return
    report("main set, report part", "main", True)
    report("fresh set", "fresh", False)
    if "--zh" in sys.argv:
        report_zh(sys.argv[sys.argv.index("--zh") + 1])
    if "--timing" in sys.argv:
        timing()


if __name__ == "__main__":
    main()
