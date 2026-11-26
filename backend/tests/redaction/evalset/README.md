# Evaluation set for the name detector (#19)

Synthetic only: invented people, invented companies. Written once and frozen (never tuned on).

- `main/`: 2,178 texts with 2,490 names (en, fr, de, es, it: 20 names each; zh: 15), four styles (normal,
  surname in capitals, all capitals, lower case), six contexts (signature, contact, plain list, prose,
  table, name split by a line break); 180 ordinary lines without a person; 40 name + job title lines.
  Ids with `id % 10 < 3` are the tuning part, the others the report part (the figures are on the report part).
- `fresh/`: 405 more names (12 per language, three styles, list/split/prose) and 60 ordinary lines, written
  before the detector was measured and not used to choose anything.

Items: `{id, lang, style, ctx, text, spans}` (names), `{id, lang, text}` (ordinary),
`{id, lang, text, name_span, title_span}` (titles). Spans are character offsets.

Reproduce the figures: `cd backend && make -C .. fetch-model && uv run python -m tests.redaction.measure_detector`.

## Chinese set for #100 (`zh/`)

Written once by `tests/redaction/make_zh_set.py` (fixed seed) before any change to the detector, then frozen:
the two files are never regenerated or edited. Same split (ids with `id % 10 < 3` tune, the others report).

- `names.jsonl`: 478 texts with 587 names, Han (three characters, two characters, two-character surnames,
  middle dot, traditional, with a title) and romanised (family-given, given-family, capitals, Hong Kong, Taiwan
  with hyphen, with a title), in nine contexts (signature, contact, plain list, prose, table, name split by a
  line break, label then name on the next line, name alone on its line, Chinese page extract mixed with Latin
  text), and 24 texts with the same person written twice. Items: `{id, lang, script, ntype, ctx, text, spans,
  scripts, title_spans}`; a title in `title_spans` must stay readable.
- `nonperson.jsonl`: 218 texts with 275 companies, places and product words (Han and pinyin, some with a
  surname), among them the invented "Suzhou Zi Jin Plastic Co., Ltd" in 12 cases (alone, in a sentence, in a list of suppliers, in a
  quote of a collected page, in a table, in a page extract) among them the public sentence of bericap.com the
  owner asked for. Items: `{id, lang, kind, ctx, text, items, suzhou}`; no character of an item
  may be removed.

Figures: `uv run python -m tests.redaction.measure_detector --zh tune` (prints the failing cases) and
`--zh report` (figures only; run once, at the end). Baseline before the change: `BASELINE-100.md`.
