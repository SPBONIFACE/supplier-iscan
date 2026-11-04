# Reference sets of the evaluation harness (#22)

- `identity`: the three recorded cases of #16, loaded from `backend/tests/identity/cases/` (not copied).
- `retrieval`: the cases of #20, loaded from `backend/tests/collection/cases/retrieval_cases.json` (not copied).
- `extraction.json`: happy path, negative (`not_found`, never an invented value), edge (accents, CJK, an injected instruction).
- `assessment.json`: empty until #25; its format is described in the file and validated by the loader.

All cases use synthetic or public companies, no personal data, and source texts in redacted form.
The `recorded` model answers belong to the fake provider (plumbing only); live runs ignore them.
When a case changes, raise `CASE_SET_VERSION` in `eval/cases.py`.
