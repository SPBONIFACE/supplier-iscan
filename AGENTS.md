# AGENTS.md

**Supplier iScan**: evidence-based supplier profiles for procurement teams. A buyer names a supplier and confirms
its identity in a short chat; the app collects public evidence, fills a fixed profile in which every fact carries a
verbatim quote, its source and date (or "No public evidence found"), and drafts an assessment that cites those facts.
The buyer reviews everything. The AI proposes; the buyer decides.

Final project of the AI Dev Tools Zoomcamp. Its own git repository (`supplier-iscan`); the course repository around it
does not apply here.

## Commands

Created by the first (scaffold) issue; until then, there is no code.

- `make install`: install backend and frontend dependencies
- `make test`: unit and integration tests, backend and frontend
- `make lint`: linters and type checks
- `make run`: the whole system, database included

Python is managed with `uv`, JavaScript with `pnpm`. Never `npm install` or `npx`.

## Rules

- `_docs/product/spec.md` is the product specification: implement against it. A change of scope is agreed with the
  owner first, never made silently.
- `openapi.yaml` is the API contract. It changes before the code, never after.
- Design first: no frontend work before the owner has approved the mock-ups for that screen.
- No new dependency without asking. Pinned versions, lockfiles committed.
- Personal data is redacted before any LLM call; LLM output is structured and schema-validated.
- Secrets are referenced by name; never read, write or commit a `.env` file.
- Commit only on a branch, and push or merge only when the owner says so.

## Documents

- `README.md`: what the product does and how to run it
- `_docs/product/spec.md`: user flows, acceptance criteria, data model, security model, safeguards
- `_docs/process/process.md`: how work flows (PM → SWE → QA, verdicts, orchestration level)
- `_docs/process/task-template.md`: the four-section issue template
- `_docs/team/{pm,swe,qa}.md`: role contracts; wrappers in `.claude/agents/`

Local working documents of the owner, if present, are described in `CLAUDE.local.md` (not part of this repository).
