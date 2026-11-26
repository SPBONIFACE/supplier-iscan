# Baseline for #100 (current `main`, before any detection change)

Measured on 26-27 Nov 2026 with `uv run python -m tests.redaction.measure_detector`, real model
(GLiNER `gliner_multi_pii-v1` at the pinned revision, threshold 0.9, spaCy `zh_core_web_sm` 3.8.0),
4 threads, one MacBook (arm64, CPU only). Names hidden, in percent, report part of the main set.

## Main set, report part (1,746 names, 126 ordinary lines)

| lang | normal | all_caps | lower | surname_caps | signature | contact | list | prose | table | split |
|---|---|---|---|---|---|---|---|---|---|---|
| en | 99 | 99 | 98 | 99 | 100 | 100 | 93 | 100 | 99 | 100 |
| fr | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| de | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| es | 99 | 99 | 99 | 100 | 100 | 100 | 100 | 100 | 96 | 100 |
| it | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| zh (15 names per context) | 74 | - | - | - | 86 | 100 | 100 | 86 | 100 | 0 |

- All names hidden: 99. Lowest Latin: normal 99 (en), all_caps 99 (en), lower 98 (en); plain list 93 (en).
- Ordinary lines altered: 3 of 126 = 2.4% (es "Hijos de Villaescusa", it "Gentili signori",
  zh "阿尔法"); of the 21 Chinese ordinary lines in the report part, 1 is altered.
- Name hidden and title kept: 27 of 28.

## Fresh set (540 names, 60 ordinary lines)

All languages and styles 100% (list, split, prose, normal, all_caps, lower). Ordinary lines altered:
2 of 60 = 3.3% (fr ", Monsieur", es "Atentamente").

## Time and memory (`--only-timing`, 4 threads, nothing else running)

| | baseline |
|---|---|
| 100 kB mixed Latin text, plain | 73 s (a first run: 67 s) |
| 100 kB mixed Latin text, in capitals | 62 s (first run: 56 s) |
| 100,000 characters of Han text | 125 s |
| peak memory of the process (`ru_maxrss`, model included) | 2.13 GB |
| model load | 19 s (15 to 32 s, disk cache) |

The Han figure on this machine is above the 90 s ceiling of the acceptance criteria already before
any change; the "baseline + 10%" part of the criterion is the one that can be measured here.
Runs vary by up to 15% from one run to the next on a laptop (a second full run gave 82 s and 105 s
for the two Latin texts while other work ran on the machine), so the timing is always taken alone.
