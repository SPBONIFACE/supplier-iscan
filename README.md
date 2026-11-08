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

## About the crawler

If you found a link to this page in your website's logs, it was left by the Supplier iScan crawler
(`SupplierIScan/1.0`). A buyer starts it for one named supplier at a time; it reads a few public pages about that
company to build a sourced profile. It follows `robots.txt` and text-and-data-mining reservations
(`tdm-reservation`, `tdmrep.json`), makes at most 200 requests across at most 10 websites per run, and never logs in,
fills in forms or gets around access controls.

To stop it visiting your site, add this to your `robots.txt`:

```
User-agent: SupplierIScan
Disallow: /
```

or open an issue in this repository naming your domain, and it will be added to the crawler's suppression list.
Someone running their own instance of Supplier iScan sets their own contact page (`CRAWLER_CONTACT_URL`).

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

Every run has a cost budget, `RUN_BUDGET_EUR` (EUR, above 0, at most 100000; the application has no default and
refuses to start without it). A run that reaches it ends `partial`, keeps what it produced and says which sections
were not covered. `make run` sets it to 5 through `docker-compose.yml` for local use; set your own in `.env` or the
environment.

Collection of public evidence is on in every run. Its worker needs `CRAWLER_CONTACT_URL` (`make run` uses a local
placeholder), the public page named in
the User-Agent of every request to a supplier's site; without it a run fails at collection. Every outbound request of
a run is capped (`COLLECT_MAX_REQUESTS`, default 200, permission checks included) as are the distinct websites
contacted (`COLLECT_MAX_DOMAINS`, default 10).

Extraction fills the `fact` fields of the profile from the stored sources and keeps a value only when its quote is
found in the cited source. It sends at most `EXTRACT_MAX_INPUT_CHARS` characters of source text per call (default
20000), and gives a certification fact the link of `IAF_CERTSEARCH_URL` (default `https://www.iafcertsearch.org/`).

### Observability

The API and the worker write JSON logs to standard error (`timestamp`, `level`, `service`, `logger`, `message`, and
`trace_id` and `span_id` inside a trace; an exception is logged by its type and stack only, never its message), and
build one trace per run: the request that starts it, the queued job (the trace ID travels in the job), each stage
(`run.stage`: identity, collection, extraction, assessment) and each provider call. Spans, metrics and logs hold
identifiers, statuses and counts only: attributes come from an allow-list, never from a request body, a prompt, a
source text or a supplier name. SDK debug logging (`ANTHROPIC_LOG`, `PERPLEXITY_LOG`, etc.) is switched off at start.

Settings (names only; values in the environment):

- `OTEL_EXPORTER_OTLP_ENDPOINT`: base address of an OTLP/HTTP collector, for example `http://localhost:4318`. Empty
  (the default): nothing is exported and the application runs as usual. Credentials for a collector, if it needs
  any, go in `OTEL_EXPORTER_OTLP_HEADERS` (read by the OpenTelemetry SDK).
- `TELEMETRY_EXPORT_TIMEOUT_SECONDS`: how long one export may take before it is dropped (default 5). Export runs
  in background threads, so an unreachable collector never fails or slows a request or a run.
- `DATABASE_STATEMENT_TIMEOUT_SECONDS`: the longest a database statement may run (default 30); a database that
  accepts connections but does not answer gives a 503 (or a paused run), not a hanging request. Migrations run with
  no statement timeout. The access log (one line per request) has the method, the route template, the status and the
  duration, never the path or the query string; uvicorn's own access log is switched off.

Metrics (names as exported; Prometheus shows dots as underscores): `iscan.runs.started`, `iscan.runs.finished`
(attribute `iscan.status`: `completed`, `partial`, `insufficient_sources`, `stopped`, `failed`; a paused run is not
finished), `iscan.run.stage.duration` (seconds, by `iscan.stage`), `iscan.llm.tokens` (by `iscan.token_type`),
`iscan.llm.cost` (EUR), `iscan.llm.calls` (by `iscan.outcome`), the LLM ones by role, provider and model, and
`iscan.http.requests` (by route template and status; a rise in 503 covers a database that does not answer).

The profile-run failure rate (what the alert of #53 reads) is failed runs divided by finished runs over a window.
In PromQL, with the usual conversion of names:

```
sum(increase(iscan_runs_finished_total{iscan_status="failed"}[1h])) / sum(increase(iscan_runs_finished_total[1h]))
```

It has no value, hence no alert, when no run finished in the window. `app.telemetry.failure_rate` computes the same
quantity from the counts and is covered by a test.

For a local collector, point the endpoint at any OTLP/HTTP receiver, for example an OpenTelemetry Collector with the
`otlp` receiver on port 4318. The optional Docker Compose telemetry stack (Collector, Prometheus, Loki, Tempo,
Grafana) belongs to #52 and #53.

Diagnostic for a provider response that fails validation: `make provider-shape CONFIG=<retrieval configuration id>`
makes one retrieval call on a synthetic public query and writes the shape of the response (field names, types, string
and list lengths; no text, no URL, no key) to `diagnostics/` (git-ignored), which is safe to share. Only this command
writes it; the application never does. Do not type the key on the command line (it stays in the shell history):
export it first through a hidden prompt (in zsh, `read -s "PERPLEXITY_API_KEY?Key: "; export PERPLEXITY_API_KEY`) or
load it from your own secret store, then run the command. It uses the same approved configuration file, price table
and name-detection model as a live `make eval`.

Check that a structuring configuration accepts the app's requests: `make provider-check CONFIG=<structuring configuration id>`
makes one tiny synthetic structured call (a schema with the same kind of constraints as the app's) and prints `OK`, or
the provider's error type and message, and nothing else (no prompt, no answer, no key). Set the key as above, through a
hidden prompt (for Anthropic, `read -s "ANTHROPIC_API_KEY?Key: "; export ANTHROPIC_API_KEY`), never on the command line.
A call the provider rejects is logged by the application, for every provider, with the provider's error type and message
(they describe the request, never its content).

### Commands

| Command | What it does |
| :--- | :--- |
| `make install` | Installs the backend and frontend dependencies from the lockfiles (`uv.lock`, `pnpm-lock.yaml`), without changing them, and fetches the name-detection model (below) |
| `make fetch-model` | Fetches the name-detection model used by redaction: about 1.2 GB, pinned revision, sha256-checked, into `~/.cache/supplier-iscan` (outside the repository; override with `REDACTION_MODEL_DIR`). Files already there are kept; nothing is downloaded at run time |
| `make eval CONFIG=<id> PROMPTS=<path>` | Evaluates the LLM features against the reference sets in `eval/` and writes a Markdown and JSON report to `eval/reports/` (not committed). `CONFIG=fake` replays recorded answers: plumbing only, no key, no network. A live run needs the key of the configuration, by name, and stays local. A reviewer rating file (`RATINGS=`, template `eval/reviewer_ratings.template.csv`) gives the "judged useful" metric; without it the report says "not rated" |
| `make provider-shape CONFIG=<id>` | One live retrieval call on a synthetic public query; writes the response shape (names and types only) to `diagnostics/` (git-ignored). See Configuration |
| `make provider-check CONFIG=<id>` | One tiny live structured call on a synthetic prompt; prints OK or the provider's error type and message. See Configuration |
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

### In a browser (GitHub Codespaces)

For a machine where Docker or the toolchain cannot be installed. The dev container in `.devcontainer/` provides
Python 3.13.16 with uv, Node.js 24.22.1 with pnpm (through Corepack), Docker and a PostgreSQL 16 database for the
tests. Nothing to install by hand.

1. On the repository page on GitHub: **Code** > **Codespaces** > **Create codespace on main**. The first creation
   takes a few minutes; it ends by running `make install`.
2. In the codespace terminal, the same commands as on a laptop: `make lint`, `make test`, `make run`. The database
   used by the tests starts with the codespace; after `make stop`, start it again with
   `docker compose up -d --wait db`. To check it: `docker compose exec db psql -U supplier_iscan -c 'select version()'`.
3. After `make run`, open the **Ports** tab and open the forwarded address of port **5173** (Frontend). Port 8000
   is the API (`/health`). The database port is not forwarded. Forwarded ports are private to the account that
   opened the codespace: keep them private.

The API accepts browser requests from the codespace's own frontend address and from `http://localhost:5173`:
`devcontainer.json` sets `CORS_ALLOWED_ORIGINS` to these two origins, no wildcard. The database and administrator
credentials are the local-only defaults of `docker-compose.yml`.

No key is needed to install, lint, test or run. To use an LLM provider, add its key as a Codespaces secret under
the same name as in `.env.example` (for example `ANTHROPIC_API_KEY`): GitHub **Settings** > **Codespaces** >
**Secrets** > **New secret**, select this repository, then restart the codespace. Do not create a `.env` file in
the codespace.

Codespaces usage counts against the free monthly allowance (core hours and storage) of the GitHub account that opens
the codespace; stop or delete the codespace when you are done.
## Deployment

The hosted instance runs on Google Cloud Run (EU) with a Neon PostgreSQL database (EU). Setup is done once by the
owner with the step-by-step [owner guide](_docs/operations/owner-deployment-guide.md); the reasoning behind sizes,
the worker and telemetry is in [`_docs/operations/cloud-run-sizing.md`](_docs/operations/cloud-run-sizing.md).

- **Dev**: every push to `main` whose CI run is green runs `.github/workflows/deploy-dev.yml`: build the API,
  worker and frontend images, check them (`deploy/check_image.py`: no `.env`, private key, `_private/` content or
  credential pattern in any layer; size report), push them to Artifact Registry, migrate the dev database
  (`python -m app.migrate`, a Cloud Run job), deploy, call `GET /health`. The new revision gets traffic only after
  its health check passes.
- **Production**: manual (`.github/workflows/promote-prod.yml`), behind the GitHub environment `production` with a
  required reviewer. It deploys the exact image digests running in dev, with the same migration and health gates.
  Rollback: send traffic back to the previous revision (guide, step 16).
- **Until Google Cloud is set up** (repository variables `GCP_PROJECT_ID`, `GCP_REGION`,
  `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_DEPLOY_SERVICE_ACCOUNT`) the deployment workflows print a notice and skip;
  CI stays green.
- **No long-lived key anywhere**: GitHub signs in to Google Cloud with Workload Identity Federation. Application
  secrets (database URL, administrator, provider keys) live in Google Secret Manager as `iscan-<env>-<name>`, are
  passed to the services by name at run time and never enter an image, a workflow or a file.
- **Settings** per environment are in `deploy/env/` (`*.yaml`: application settings by name; `*.conf`: Cloud Run
  sizing). The API and the worker are one image; the frontend image takes `API_UPSTREAM_URL` at start, so the same image
  serves every environment.
- **Images CI** (`.github/workflows/images.yml`) builds the images on the runner for every change to them, checks
  them, and runs a redaction smoke test inside the built backend image, offline and with a 4 GB memory limit; the
  load time and peak memory appear in the run summary.
- **Telemetry**: Google Cloud Trace and Cloud Monitoring through an OpenTelemetry Collector sidecar
  (`deploy/collector`); the application setting is `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`.
- **One address**: the browser talks to the frontend service only; its nginx forwards `/api/` to the API service
  (`frontend/deploy/`), so the session cookie stays on one site and no domain name is needed
  (`cloud-run-sizing.md`, "One address"). `deploy/check_proxy.py` tests this on the built image in CI.
- **Worker off by default**: the deployment creates the worker with zero instances in dev and production and never
  switches it on; the owner switches it on for a run or a demo and off afterwards (guide, step 17). With no worker
  a started run waits in the queue.
