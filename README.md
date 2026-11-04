# Supplier iScan

**Evidence-based supplier profiles for procurement teams.** Every fact comes with its source, or the app says
there is none.

> Status: specification approved; development in progress (final project of the
> [AI Dev Tools Zoomcamp](https://github.com/DataTalksClub/ai-dev-tools-zoomcamp)).

## The problem

Buyers and category managers need a reliable picture of a supplier (who it really is, where it produces, which
certifications and sustainability commitments it holds) when they source, qualify or prepare a negotiation. Today
they assemble it by hand from websites, PDF reports and searches. It takes hours per supplier, the result is rarely
sourced, and it goes stale. Generic AI chatbots are faster but invent facts and citations, so their output cannot go
into a supplier qualification file.

## What Supplier iScan does

1. **Confirms who the supplier is.** A short chat with an AI agent: you type a name, it proposes the matching company
   from public registries, you confirm or correct. Hints never exclude the right company.
2. **Collects public evidence.** Website pages, PDF reports and web search, adapting its strategy when a source fails,
   and respecting each site's crawling and text-mining choices.
3. **Fills a fixed profile, fact by fact.** Every value carries a short verbatim quote, its source and date, checked
   automatically against the source text. A value without a verifiable quote is rejected; missing information reads
   "No public evidence found", never "does not have". Each fact is labelled "supplier's own claim" or
   "third-party source".
4. **Drafts an assessment you can audit.** Strengths, weaknesses, risk indicators and fit against your own criteria:
   every statement cites the facts it rests on, or says which evidence is missing and where to find it. No black-box
   score.
5. **Leaves the decision to you.** You approve or correct every fact and every statement, compare suppliers side by
   side, and export a PDF.

The AI proposes; the buyer decides.

## Design principles

- **Grounding over fluency:** quotes are verified in code, not trusted from the model.
- **Privacy by design:** personal names and contact details are redacted before any text reaches an AI provider.
- **Provider choice:** Claude, Gemini, OpenAI, Mistral or Perplexity, chosen per role (retrieval, structuring), with
  structured, schema-validated output only.
- **Transparency:** the chat says it is an AI; every AI statement shows its model, date and review status.
- **English and French** interface.

## Architecture (planned)

| Layer | Technology |
| :--- | :--- |
| Frontend | React, Vite, TypeScript (pnpm), react-i18next |
| Backend API | Python 3.13, FastAPI (uv), OpenAPI contract first |
| Profile runs | Worker with a PostgreSQL-backed job queue |
| Data | PostgreSQL 16 |
| PDF | WeasyPrint |
| Deployment | Docker Compose locally; Google Cloud Run and Neon (EU) |
| Observability | OpenTelemetry: metrics, traces and logs sharing a trace ID |

## How it is built

Spec-driven and agent-assisted:

- **Specification first:** [`_docs/product/spec.md`](_docs/product/spec.md): user flows, acceptance criteria,
  data model, security model, safeguards.
- **An agent team** with written contracts: a PM grooms each issue, a software engineer implements it, QA verifies it
  against the acceptance criteria and posts PASS, FAIL (defect) or FAIL (criteria).
  See [`_docs/team/`](_docs/team/) and [`_docs/process/process.md`](_docs/process/process.md).
- **Context for agents:** [`AGENTS.md`](AGENTS.md).
- **Agent extension pack:** [`agent-pack/`](agent-pack/README.md): an `evidence-wording` skill, a read-only MCP
  server over `openapi.yaml`, and a hook that blocks `.env` access and `npm`/`npx` (Claude Code; the skill and the
  server also work with other agent tools).
- **Task tracker:** the GitHub issues of this repository.

## Running it

### Prerequisites

| Tool | Version | Pinned in |
| :--- | :--- | :--- |
| Docker with Compose v2 | any recent | |
| GNU Make | any | |
| uv | 0.12.24 | `backend/pyproject.toml` (`required-version`) |
| Python | 3.13.16 (uv downloads it if it is missing) | `backend/.python-version` |
| Node.js, with Corepack | 24.22.1 | `frontend/.node-version`, `frontend/.nvmrc`, `engines` in `frontend/package.json` |
| pnpm | 11.28.5 (Corepack installs it: `corepack enable pnpm`) | `packageManager` in `frontend/package.json` |

`make install` stops with an error if the uv or Node.js version differs from the pinned one.

### Configuration

```sh
cp .env.example .env
```

This step is optional. `.env.example` lists the secret names (database URL and password, the first administrator's
credentials, LLM provider API keys) with empty values. Fill in your own values in `.env`, which is never committed.
Without a `.env` file and without any provider key, the system starts with local defaults. Those defaults, for the
database and for the administrator, are for local use only.

On first start (empty database), the API creates the local administrator from `ADMIN_EMAIL` and `ADMIN_PASSWORD`.
For `make run`, `docker-compose.yml` provides local-only defaults: email `admin@localhost`, password
`local-only-admin-change-me`. To use your own, set both in `.env` or in the environment before the first start, for
example `ADMIN_EMAIL=you@example.com ADMIN_PASSWORD='…' make run`. They are read on first start only: changing them
afterwards changes nothing unless you start from an empty database (`docker compose down -v` deletes the local
data). Outside Docker Compose the application has no default and refuses to start without both.

Collection of public evidence is on in every run. Its worker needs `CRAWLER_CONTACT_URL`, the public page named in
the User-Agent of every request to a supplier's site; without it a run fails at collection. Every outbound request of
a run is capped (`COLLECT_MAX_REQUESTS`, default 200, permission checks included) as are the distinct websites
contacted (`COLLECT_MAX_DOMAINS`, default 10).

Extraction fills the `fact` fields of the profile from the stored sources and keeps a value only when its quote is
found in the cited source. It sends at most `EXTRACT_MAX_INPUT_CHARS` characters of source text per call (default
20000), and gives a certification fact the link of `IAF_CERTSEARCH_URL` (default `https://www.iafcertsearch.org/`).

### Commands

| Command | What it does |
| :--- | :--- |
| `make install` | Installs the backend and frontend dependencies from the lockfiles (`uv.lock`, `pnpm-lock.yaml`), without changing them, and fetches the name-detection model (below) |
| `make fetch-model` | Fetches the name-detection model used by redaction: about 1.2 GB, pinned revision, sha256-checked, into `~/.cache/supplier-iscan` (outside the repository; override with `REDACTION_MODEL_DIR`). Files already there are kept; nothing is downloaded at run time |
| `make test-model` | The tests that use the real model (slow; `make test` leaves them out and uses a small fake detector) |
| `make lint` | Linters, format checks and type checks (Ruff and mypy; Biome and TypeScript) |
| `make test` | Backend and frontend tests, including the API contract test against `openapi.yaml` |
| `make run` | Starts the database, the API and the frontend with Docker Compose (`make stop` stops them) |

### Local URLs

| Service | URL |
| :--- | :--- |
| Frontend | http://localhost:5173 |
| API | http://localhost:8000 (port 8000, fixed in `docker-compose.yml`); health check: http://localhost:8000/health |
| Database | `127.0.0.1:5432`, reachable from this machine only |

Every port is published on `127.0.0.1` only. The API accepts browser requests from the origin set in
`CORS_ALLOWED_ORIGINS` (default `http://localhost:5173`). The API contract is [`openapi.yaml`](openapi.yaml).
