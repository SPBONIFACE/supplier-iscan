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

## New Chinese set (`evalset/zh/`), baseline on current `main`

Written and frozen before any detection change. Names hidden, in percent (number of names). Report
part: 334 texts, 418 names, 192 non-person items; tuning part: 144 texts, 169 names, 83 items. A
name written twice in one text (`dual`) is counted once as Han and once as romanised.

| | tuning part | report part |
|---|---|---|
| Han names hidden, all | 70 (89) | 74 (217) |
| romanised names hidden, all | 92 (80) | 90 (201) |
| non-person items altered | 11/83 = 13.3% | 30/192 = 15.6% |
| Suzhou Zi Jin cases altered | 0/16 | 0/10 |
| Han: name hidden and title kept | 26% (23) | 10% (30) |
| romanised: name hidden and title kept | 84% (19) | 67% (36) |

Report part, Han, by context: alone 46 (13), contact 90 (20), dual 70 (20), list 84 (55), nextline 100
(19), page 75 (16), prose 50 (22), signature 58 (19), split 40 (15), table 94 (18).
Han, by type: three characters (h3) 83 (53), two characters (h2) 71 (34), two-character surname (hc)
58 (31), middle dot (hd) 79 (24), traditional (ht) 72 (25), with a title (hT) 77 (30), dual 70 (20).

Report part, romanised, by context: alone 82 (17), contact 95 (20), dual 30 (20), list 94 (51),
nextline 100 (12), page 100 (12), prose 100 (21), signature 100 (18), split 100 (12), table 100 (18).
Romanised, by type: family-given (rfg) 97 (38), given-family (rgf) 100 (29), capitals (rcaps) 93
(27), Hong Kong (rhk) 100 (25), Taiwan with hyphen (rtw) 96 (26), with a title (rT) 92 (36), dual
30 (20).

Report part, non-person items altered, by kind: company_latin 3/40, company_surname 3/34,
company_han 0/24, place_han 2/22, place_pinyin 10/30, product 12/37, suzhou 0/10.
