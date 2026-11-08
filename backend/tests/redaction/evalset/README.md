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
