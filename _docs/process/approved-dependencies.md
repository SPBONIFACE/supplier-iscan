# Approved dependencies

**Approved by the owner on 27 Oct 2026** (`process.md` § Delivery mode). A SWE installs a package listed here without asking again, following the rules below. Anything not listed, or a new major version, is an owner gate.

Drafted 27 Oct 2026 by the SWE from the open issues (#3 to #57).
Versions come from the PyPI JSON API, the npm registry, GitHub releases and OSV (advisories), queried on 27 Oct 2026.

## Owner decisions (27 Oct 2026)

1. **LLM access:** the five official SDKs (`anthropic`, `openai`, `google-genai`, `mistralai`, `perplexityai`), versions as listed.
2. **Name detection (revised 3 Nov 2026, owner decisions D-066 and D-068):** GLiNER `urchade/gliner_multi_pii-v1` (Apache-2.0) on CPU PyTorch plus the precise rules of the engine; spaCy stays only with `zh-core-web-sm`, for text with Han characters. `en-core-web-sm`, `de-core-news-sm` and `xx-ent-wiki-sm` are **removed**. Measured (issue #98, synthetic set, report part): spaCy baseline 66% of names hidden and 6.3% of ordinary lines altered; GLiNER plus rules 98 to 99% and 2.4%.
3. **Version policy:** a SWE may take a newer patch or minor version of a listed package (at least 14 days old, no known advisory, no install script, no new direct dependency) and states it in the pull request; a new major version needs the owner.
4. **Security exceptions to the 14-day rule:** `pypdf` 6.21.2, `pillow` 13.0.0, `undici` ≥ 8.12.2 (dev, transitive) are accepted.
5. **Non-Latin text in the PDF:** IBM Plex Sans JP, KR and SC (SIL OFL 1.1), consistent with the design brief (#3), instead of Debian `fonts-noto-cjk`.
6. **Observability, as in the course's Part 4 (DevOps and Observability):** the application exports OTLP with the OpenTelemetry SDK listed below. Locally, an optional Docker Compose part runs the same stack: OpenTelemetry Collector (`otel/opentelemetry-collector-contrib`), Prometheus (`prom/prometheus`), Loki (`grafana/loki`), Tempo (`grafana/tempo`) and Grafana (`grafana/grafana`), with Grafana alert rules calling the on-call responder through a webhook (#51, #53). These images are approved; their versions are pinned by tag and digest at install, at least 14 days old. The deployed telemetry backend, the alert relay and the on-call runtime (`anthropics/claude-code-action` or a script on `anthropic`) are decided with the deployment in Sprint 7 (#52, #53).
7. **Supplier card fonts**: Piazzolla and Barlow Semi Condensed (SIL OFL 1.1), self-hosted woff2, from the tearsheet redesign (#163).

## Rules the list follows

- **Direct dependencies only.** Transitive packages are resolved by `uv lock` / `pnpm install` under the existing age
  gates (`exclude-newer` in `backend/pyproject.toml`, `minimumReleaseAge: 20160` in `frontend/pnpm-workspace.yaml`).
  Notable transitive packages are named in the audit notes.
- **Age.** Every version was released on or before 13 Oct 2026 (at least 14 days ago), except the three security
  exceptions marked **SEC**. At install time the SWE moves `exclude-newer` forward to (install date − 14 days) and, for a
  SEC package only, adds a per-package `exclude-newer-package` entry (uv) or `minimumReleaseAgeExclude` (pnpm).
- **No install scripts.** Every Python package installs from a wheel (`no-build = true` stays); every npm package
  has `hasInstallScript: false` (the `prepare` scripts listed by i18next, react-i18next, jsdom and undici run only in
  their own repositories, never on install). No exception is needed.
- **No advisory.** OSV reports no known vulnerability for any version below (checked 27 Oct 2026).
- **Already locked, no change:** `fastapi`, `uvicorn`, `psycopg[binary]` (DB driver), `pydantic`, `opentelemetry-api`
  (pulled by FastAPI 0.143), `pytest`, `ruff`, `mypy`, `pyyaml` (dev), React, Vite, Vitest, Biome, TypeScript.

## Decisions taken with the standard library or installed packages (no new dependency)

| Job | Decision | Why |
| :--- | :--- | :--- |
| PostgreSQL job queue (#13, #43, #44, #45) | Own queue table on psycopg: `SELECT … FOR UPDATE SKIP LOCKED`, a lease column with expiry for reclaim, optional `LISTEN/NOTIFY` wake-up | ~150 lines, fully testable; a library (procrastinate, ~10 packages) would add its own schema and worker model for little gain |
| Content files: profile definition, prompt set, country table, archive schema (#21, #26, #44, #55) | JSON files, `json` (stdlib) + `jsonschema` (promoted to runtime, see table) | Issues say JSON and "JSON Schema validator already approved"; no YAML at runtime |
| HTML text extraction and link discovery (#18) | `html.parser` (stdlib): drop `script/style/noscript/template/nav/header/footer/aside`, `role=navigation`; collect links; read `<meta charset>` | Fixture sites cover the criteria; a parser library (lxml, BeautifulSoup, trafilatura) adds 1 to 10 packages |
| `sitemap.xml` / sitemap index (#18) | `xml.etree.ElementTree` + size cap; `gzip` for `.xml.gz` | Python 3.13 with expat ≥ 2.4.1 is safe against billion-laughs and quadratic blow-up and never fetches external entities; `defusedxml` not needed |
| Email redaction (#19) | `re` | A conservative pattern is enough for addresses |
| Unicode and typography normalisation, accent folding (#14, #18, #19, #23) | `unicodedata` | NFC / NFKD |
| Per-domain rate limit, GLEIF throttle, Wikidata concurrency, `Retry-After`, registry cache (#14, #18) | own code on the HTTP client below; cache in a DB table or keyed in-memory | No `tenacity` / `aiolimiter` needed |
| URL guard against private, loopback, link-local targets (#15) | `ipaddress`, `socket.getaddrinfo`, a custom transport that connects only to the vetted address | |
| Recorded HTTP fixtures (#12, #14, #22) | `MockTransport` of the HTTP client + JSON fixture files | No `respx` / `vcrpy` |
| Sessions (#8) | Server-side session table, token from `secrets` | No `itsdangerous` |
| JSON logs with `trace_id` (#51) | `logging` + a ~30-line JSON formatter | No `python-json-logger` |
| ZIP packages and archives (#42, #44) | `zipfile` | As the issues require |
| Eval harness CLI and reports (#22) | `argparse`, `json`, Markdown by string building | |
| Image secret scan in CI (#52) | Script over `docker save` output (stdlib `tarfile`) | No trufflehog/gitleaks |
| Settings (all) | Existing `app/config.py` pattern (`os.environ`) | No `pydantic-settings` |
| Frontend browser-language detection, date and number formatting (#31) | `navigator.languages` + `localStorage` (10 lines); `Intl` | No `i18next-browser-languagedetector`, no date library |
| Frontend "no direct fetch" rule (#31) | Biome `noRestrictedGlobals` / a test | |
| PDF text and metadata read-back in tests (#39) | `pypdf` (already in this list for #18) | |

## Backend: runtime (`backend/pyproject.toml`, `[project] dependencies`)

| Package | Exact version | Runtime/dev | Licence | First issue | Why | Audit note |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `sqlalchemy` | 2.0.54 | runtime | MIT | #8 | Typed models and query building on the installed psycopg driver; one scoping helper (#10) composes `where(organisation_id == …)` instead of hand-built SQL | Mature 2.0 series (2.1.0 final only since 24 Sep). Pulls `greenlet` 3.5.6 (MIT/PSF, wheel). Sync engine only. |
| `alembic` | 1.20.0 | runtime | MIT | #8 | Migrations; detects multiple heads when parallel-wave branches each add one, so collisions fail CI instead of silently diverging; #52 runs `alembic upgrade head` | Pulls `mako` 1.4.3, `markupsafe` 3.0.4. |
| `argon2-cffi` | 25.1.0 | runtime | MIT | #8 | Argon2id hashing (spec: argon2); stdlib has none | Pulls `argon2-cffi-bindings` 26.1.0 (abi3 wheel), `cffi` 2.1.1, `pycparser`. Hynek Schlawack; the reference Python binding. |
| `httpx2` | 2.13.1 | runtime | BSD-3-Clause | #14 | The one HTTP client for registries, crawling, PDFs and the URL guard (#15). Successor of `httpx` (now maintained under the pydantic organisation); Starlette 1.7's `TestClient` already prefers it and warns on `httpx`; the Anthropic, OpenAI, Mistral and MCP SDKs depend on it | Pulls `httpcore2` 2.13.1, `h11` (locked), `truststore` 0.10.5 (system trust store: the image keeps `ca-certificates`). Replaces dev `httpx` 0.28.1 (pre-1.0, last release Dec 2024). |
| `protego` | 0.7.0 | runtime | BSD-3-Clause | #17 | robots.txt per RFC 9309: `*` and `$` wildcards, longest-match, per-agent groups (needed to detect GPTBot/ClaudeBot/… blocks). `urllib.robotparser` has no wildcard support and uses first-match, so it would allow paths a site disallows | **Pre-1.0: audited.** Scrapy project (Zyte); used by every Scrapy install. Pure Python, 0 dependencies, wheel only, parses strings (no network, no file access), no `exec`/`eval` (verify with `grep` at install). |
| `pypdf` | 6.21.2 **SEC** | runtime | BSD-3-Clause | #18 | PDF text and author extraction from untrusted PDFs | Released 21 Oct (6 days). **Security exception:** 6.20.1 has 7 advisories (3 HIGH: unbounded runtime on malformed xref; memory exhaustion), fixed in 6.21.0 to 6.21.2. Pure Python, 0 dependencies. Still enforce size and page caps and a time limit. |
| `phonenumbers` | 9.0.41 | runtime | Apache-2.0 | #19 | Phone-number detection in free text (`PhoneNumberMatcher`, regions FR, DE, GB, US, …) with validity checks. A regex broad enough for "+33 1 23 45 67 89", "030.123.456" would also eat SIREN/LEI numbers, revenue figures and ISO references, destroying grounded quotes | Port of Google libphonenumber; pure Python, 0 dependencies, ~9 MB of metadata. |
| `spacy` | 3.8.16 | runtime | MIT | #19 | Chinese name detection only (`zh-core-web-sm`); the en, de and xx models were removed on 3 Nov 2026 | ~25 transitive packages, all wheels: `thinc`, `numpy` 2.5.x, `blis`, `cymem`, `preshed`, `murmurhash`, `srsly`, `catalogue`, `confection`, `wasabi`, `weasel` (→ `typer`, `rich`, `cloudpathlib`, `smart-open`, `wrapt`, old `httpx`), `requests`, `tqdm`, `jinja2`, `setuptools` (runtime import). No network at run time when models are installed as packages; never call `spacy download`. Load with only the `ner` pipe. |
| `gliner` | 0.2.29 | runtime | Apache-2.0 | #19 | Person-name detection for redaction (D-066, D-068). With the rules: 98 to 99% of names hidden in en, fr, de, es, it in normal, all-caps and lower case (spaCy baseline 83, 81, 9%), plain lists 93% (spaCy 11%), ordinary lines altered 2.4% (spaCy 6.3%) | Loads `pytorch_model.bin` with `torch.load(weights_only=True)` (checked in its source; the application also forces it). Pulls `huggingface-hub`, `safetensors`, `tokenizers`, `sentencepiece`, `tqdm`. Released 8 Sep. |
| `torch` | 2.14.1 (CPU build on Linux from `download.pytorch.org/whl/cpu`; PyPI wheel on macOS) | runtime | BSD-3-Clause | #19 | GLiNER runtime. The Linux CPU build avoids about 3 GB of CUDA libraries | Index declared `explicit` in `[tool.uv.sources]`; hashes in `uv.lock`. Pulls `sympy`, `networkx`, `mpmath`, `fsspec`, `filelock`. |
| `transformers` | 5.16.1 | runtime | Apache-2.0 | #19 | Tokenizer and encoder of the GLiNER model (required by `gliner`) | `trust_remote_code` never set; offline (`TRANSFORMERS_OFFLINE=1`). |
| `protobuf` | 7.36.2 | runtime | BSD-3-Clause | #19 | Required by `transformers` 5 to read the model's SentencePiece tokenizer (`spm.model`): without it the model does not load. Same version as already listed for the OTLP exporter (#51) | **Declared directly because no approved package pulls it in yet: flagged to the owner.** |
| Model `urchade/gliner_multi_pii-v1` | revision `1fcf13e85f4eef5394e1fcd406cf2ca9ea82351d` | runtime data | Apache-2.0 | #19 | The name detector (1.16 GB checkpoint, sha256 `3003753fba99e40645cf088c7367a2c6211fc174897dc64f1f9c147c29d18d2d`) | Not a package: `backend/scripts/fetch_model.py` downloads it at image build and in `make install` (cached in `~/.cache/supplier-iscan`) and checks sha256; never at run time. Encoder config and tokenizer files from `microsoft/mdeberta-v3-base` @ `a0484667b22365f84929a935b5e50a51f71f159d` (MIT; three small files, no weights; digests in the script). |
| `zh-core-web-sm` | 3.8.0 | runtime | MIT | #19 | Chinese NER (the only spaCy model left, united with GLiNER: Chinese 67% with GLiNER alone in the evaluation, 74% measured for the shipped union; names split over two lines are the gap) (PERSON F 0.75) for the "CJK name" criterion; run when text contains Han characters | Same, 48.5 MB. Requires `spacy-pkuseg` 1.0.1 (MIT, wheel, deps `numpy`, `srsly`). (owner decision 2). |
| `jsonschema` | 4.26.0 | runtime (moved from dev) | MIT | #21 | Startup validation of profile definition, prompt set, country table; archive schema test | Already locked; brings `attrs`, `referencing`, `rpds-py` (wheel), `jsonschema-specifications` into the image. |
| `anthropic` | 1.13.0 | runtime | MIT | #11 | Claude adapter (official SDK; spec F6 pins SDK versions) | Pulls `jiter`, `docstring-parser`, `sniffio`. 2.0.0 came out 21 Oct (too recent). Construct with `max_retries=0` so that #12 meters every attempt. |
| `openai` | 3.29.0 | runtime | Apache-2.0 | #11 | OpenAI adapter | Pulls `jiter`, `sniffio`. `max_retries=0`. |
| `google-genai` | 2.30.1 | runtime | Apache-2.0 | #11 | Gemini adapter (default structuring provider) | Heaviest SDK: `google-auth` 2.62 (→ `cryptography` 50.0.2, `pyasn1-modules`, `pyasn1`), `requests`, `urllib3`, `charset-normalizer`, `tenacity`, `websockets`, `distro`, old `httpx` 0.28.1. Released 13 Oct (exactly 14 days). |
| `mistralai` | 3.2.0 | runtime | Apache-2.0 (LICENSE file; PyPI metadata empty) | #11 | Mistral adapter | Pulls `jsonpath-python`, `python-dateutil` (+`six`), `eval-type-backport`, `opentelemetry-semantic-conventions` (beta). **Check in #11/#51:** the SDK emits its own OpenTelemetry spans; confirm no prompt or response content is recorded, or disable its tracing. |
| `perplexityai` | 0.43.8 | runtime | Apache-2.0 | #11 | Perplexity adapter (default retrieval provider), typed `search_results` | **Pre-1.0: audited.** Official (api@perplexity.ai, `perplexityai/perplexity-py`, Stainless-generated, same structure as the OpenAI SDK). Adds no transitive package beyond those above. Wheel only; contacts only the configured base URL. |
| `opentelemetry-api` | 1.45.1 | runtime (declare directly; already locked) | Apache-2.0 | #51 | Tracing and metrics API used directly by our code | |
| `opentelemetry-sdk` | 1.45.1 | runtime | Apache-2.0 | #51 | Tracer and meter providers; in-memory exporters for the tests | Pulls `opentelemetry-semantic-conventions` 0.66b1 (beta numbering of the official project, released in lockstep). |
| `opentelemetry-exporter-otlp-proto-http` | 1.45.1 | runtime | Apache-2.0 | #51 | OTLP over HTTP; off when no endpoint is configured | Pulls `opentelemetry-proto`, `protobuf` 7.36.2 (abi3 wheel), `googleapis-common-protos`, `requests`, and two 0.66b1 helper packages. gRPC exporter rejected (`grpcio`, large). **No FastAPI/contrib auto-instrumentation** (beta packages, and they record raw URLs, e.g. `/invitations/{token}`): a small ASGI middleware sets allowlisted attributes (route template, method, status). |
| `weasyprint` | 70.0 | runtime | BSD-3-Clause | #39 | Server-side PDF from HTML/CSS with the design tokens (spec, README) | Pulls `pydyf` 0.12.1, `cssselect2` 0.10.1 (pre-1.0, same maintainer CourtBouillon), `tinycss2`, `tinyhtml5`, `webencodings`, `Pyphen` (MPL-1.1/LGPL/GPL tri-licence, used unmodified), `fonttools[woff]` (+`brotli`, `zopfli`), `cffi`, `Pillow`. Provenance in PDF metadata via `<meta>` + `custom_metadata=True`. |
| `pillow` | 13.0.0 **SEC** | runtime (constraint only, transitive of WeasyPrint) | MIT-CMU | #39 | Pin a floor: 12.3.0 has 40 advisories (2 CRITICAL heap overflows, decompression-bomb bypasses), all fixed in 13.0.0 | Released 16 Oct (11 days), major version. Set as `constraint-dependencies`. Only our own image assets reach it. If WeasyPrint 70 fails with 13.0.0, the SWE stops and reports. |
| `jinja2` | 3.1.6 | runtime | BSD-3-Clause | #39 | PDF HTML templates with autoescape on | Already a transitive of spaCy; declared directly because our code imports it. |

**System packages in the backend image (#39, Debian trixie, exact `apt` versions pinned in the Dockerfile at install
time):** `libpango-1.0-0`, `libpangoft2-1.0-0`, `libharfbuzz-subset0` (brings `libharfbuzz0b`, `fontconfig`,
`libfreetype6`), plus the font files approved in #3 copied into the image (fonts are assets, not data) and IBM Plex Sans JP, KR and SC
(owner decision 5). The worker runs from the same image, so it carries PyTorch, the name model (about 1.2 GB) and WeasyPrint too; expected image
growth about 350 MB (spaCy + numpy + models ≈ 250 MB, Pango stack ≈ 60 MB, before any CJK font). Scale-to-zero cold
start is accepted by the spec.

## Backend: dev (`[dependency-groups] dev`)

| Package | Exact version | Runtime/dev | Licence | First issue | Why | Audit note |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `httpx` | 0.28.1 → **remove** | dev | BSD-3-Clause | #8 | Replaced by `httpx2` for `TestClient` | It stays in the lock as a transitive of `google-genai` and `weasel`. |
| (nothing new) | | | | | pytest, mypy, ruff, pyyaml stay | Real PostgreSQL 16 for tests: CI service and `make run` database already exist; no `testcontainers`. |

## Frontend (`frontend/package.json`)

| Package | Exact version | Runtime/dev | Licence | First issue | Why | Audit note |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `react-router` | 7.18.4 | runtime | MIT | #31 | Routing (declarative/data mode, SPA) | Deps `cookie`, `set-cookie-parser`. 16.8 M downloads/week on v7. v8.4.0 rejected for now: its dependency `@remix-run/route-pattern` is pre-1.0 and v8 adoption is a quarter of v7's. 7.18.4 released 15 Sep, same day as 8.4.0, so v7 is still patched. |
| `i18next` | 26.4.4 | runtime | MIT | #31 | i18n core (README names react-i18next) | 0 dependencies. Peer `typescript ^5 \|\| ^6 \|\| ^7`: fine with 6.0.3. |
| `react-i18next` | 17.0.16 | runtime | MIT | #31 | React bindings | Deps `@babel/runtime`, `html-parse-stringify`, `use-sync-external-store`. |
| `openapi-fetch` | 0.17.0 | runtime | MIT | #31 | Typed `fetch` wrapper over the generated `paths` types, used only inside `src/lib/api.ts`; its middleware handles the 401 redirect | **Pre-1.0: audited.** 5.3 M/week; 1 dependency (`openapi-typescript-helpers` 0.1.0, types only); no install script; calls only `fetch` with our base URL; no `eval`. |
| `openapi-typescript` | 7.13.0 | dev | MIT | #31 | Generates TypeScript types from `openapi.yaml` (`pnpm exec openapi-typescript`) | ~20 transitive (`@redocly/openapi-core` 1.x, `js-yaml`, `yargs-parser`, …), build time only. **Peer `typescript ^5.x`, project has 6.0.3:** pnpm warns, does not fail; the SWE checks that the generated file type-checks, and reports if not. |
| `@testing-library/react` | 16.3.3 | dev | MIT | #31 | Component tests | |
| `@testing-library/dom` | 10.4.2 | dev | MIT | #31 | Required peer of the above | |
| `@testing-library/user-event` | 14.6.8 | dev | MIT | #31 | Keyboard-only tests (review, comparison, forms) | Released 13 Oct (exactly 14 days). 0 dependencies. |
| `jsdom` | 30.1.2 | dev | MIT | #31 | Vitest DOM environment | ~20 transitive. **SEC note:** its dependency `undici` must resolve to ≥ 8.12.2 (8.11.2 has 3 advisories, 1 HIGH DoS; fix released 15 Oct). If #31 installs before 29 Oct, add `undici@8.12.2` to `minimumReleaseAgeExclude`. `happy-dom` rejected (2025 VM-escape advisory, less complete). |
| `axe-core` | 4.14.0 | dev | MPL-2.0 | #31 | Automated accessibility check, `axe.run(container)` asserting 0 critical | 0 dependencies; dev only, not distributed. No wrapper (`vitest-axe` is 0.1.0 from 2022). jsdom cannot compute colour contrast: contrast is checked on the mock-ups (#3 to #7, #54). |


## Agent extension pack (#56; own `uv` project `agent-pack/`, own `uv.lock`, never in an image)

| Package | Exact version | Runtime/dev | Licence | First issue | Why | Audit note |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `mcp` | 2.3.0 | runtime (of the pack) | MIT | #56 | Official MCP Python SDK (stdio server) | Pulls `mcp-types`, `httpx2`, `jsonschema`, `pydantic`, `starlette`, `uvicorn`, `sse-starlette`, `python-multipart` 0.0.32 (pre-1.0, FastAPI's form parser), `pyjwt[crypto]` (→ `cryptography`), `opentelemetry-api`. The HTTP transports are never started (stdio only, no network). |
| `pyyaml` | 6.0.3 | runtime (of the pack) | MIT | #56 | Read `openapi.yaml` (`yaml.safe_load` only) | Same version as backend dev. |
| `pytest`, `ruff`, `mypy` | 9.1.1, 0.17.0, 2.4.0 | dev (of the pack) | MIT | #56 | Same versions as the backend | |

The hook uses the standard library only.

## Dev container (#57; `.devcontainer/`)

| Item | Exact version | Licence | Why | Note |
| :--- | :--- | :--- | :--- | :--- |
| Base image `python:3.13.16-trixie` | by digest, resolved at install | PSF / Debian | Matches the pinned Python exactly (the `devcontainers/python` image's patch level drifts) | Same publisher as the backend base image |
| `ghcr.io/devcontainers/features/common-utils` | 2.7.1, by digest | MIT | Non-root `vscode` user, shell basics | |
| `ghcr.io/devcontainers/features/node` | 2.1.1, by digest, option `version: 24.22.1` | MIT | Node matching `engines.node`; pnpm through Corepack with the `packageManager` hash | |
| `ghcr.io/devcontainers/features/docker-in-docker` | 4.1.3, by digest | MIT | `make run` (Compose) and the PostgreSQL 16 container inside the codespace | Last changed 7 Oct |
| `ghcr.io/astral-sh/uv:0.12.24` | existing digest (backend Dockerfile) | MIT/Apache-2.0 | `uv` binary copied in a `.devcontainer/Dockerfile` | No third-party uv feature |

## CI and operations (#52, #53)

| Item | Exact version | Licence | Why | Note |
| :--- | :--- | :--- | :--- | :--- |
| `google-github-actions/auth` | v3.0.0 (commit `7c6bc770dae815cd3e89ee6cdf493a5fab2cc093`) | Apache-2.0 | Workload Identity Federation to Google Cloud, no long-lived key | Released 28 Aug 2025 |
| `google-github-actions/setup-gcloud` | v3.0.1 (commit `aa5489c8933f4cc7a4f7d45035b3b1440c9c10db`) | Apache-2.0 | `gcloud run deploy`, Artifact Registry push, Cloud Monitoring alert policy | `deploy-cloudrun` action not needed |
| `anthropics/claude-code-action` | v1.0.248 (commit 1d6de8cb0c237e7c15e9e1bdf973826ebae490cc, released 9 Oct 2026) | MIT | On-call agent runtime (#53) | Owner approval 11 Nov 2026 (#53, item 1). Pinned by full SHA in .github/workflows/oncall.yml |
| Google Cloud CLI (`gcloud`, with the `beta` component) | 592.0.0 | Apache-2.0 | Deploy, jobs, secret checks and worker switching in the deploy workflows (installed by `setup-gcloud`) | Version pinned in the workflows; `beta` is needed for `run worker-pools`. Approved by the owner, 7 Nov 2026 |
| `nginxinc/nginx-unprivileged` | 1.29.3-alpine, `sha256:5aea7cc516b419e3526f47dd1531be31a56a046cfe44754d94f9383e13e2ee99` | Apache-2.0 | Base of the frontend image: serves the app and forwards `/api/` as a non-root user | Image digest pinned in `frontend/Dockerfile.prod`. Approved by the owner, 7 Nov 2026 |
| `otelcol-google` (Google-built OpenTelemetry Collector) | tag `latest` of 6 Nov 2026, `sha256:871b9e716d8749660c0e5fd7e7fd5a21b04d412919ab86792528ee4cfa258f89` | Apache-2.0 | Sidecar that sends traces to Cloud Trace and metrics to Cloud Monitoring | Pinned by digest in `deploy/collector/Dockerfile`. Approved by the owner, 7 Nov 2026 |
| Base image of the alert relay `python:3.13.16-slim-trixie` | sha256:cf50a4f6ac4f026458b08d5222023d700ac806410dff5e9ca8728fa44f2b850f | PSF / Debian | deploy/alert-relay/Dockerfile (#53); same image and digest as backend/Dockerfile, no package installed | Owner approval 11 Nov 2026 (#53, item 4) |

## Already locked in the repository (recorded 3 Nov 2026 for `agent-pack/scripts/check_dependencies.py`)

These direct dependencies were in the repository before the check existed; the "Already locked, no change" rule above
named them without versions. The check compares exact versions, so they are listed here as they stand in
`backend/pyproject.toml` and `frontend/package.json`. **`spacy-pkuseg` was in no earlier table: the owner is asked to
confirm it** (Chinese word segmentation of the `zh-core-web-sm` model, direct pin added with #19).

| Package | Exact version | Runtime/dev | Note |
| :--- | :--- | :--- | :--- |
| `fastapi` | 0.143.0 | runtime | Backend |
| `uvicorn` | 0.54.0 | runtime | Backend |
| `psycopg[binary]` | 3.3.6 | runtime | Database driver |
| `spacy-pkuseg` | 1.0.1 | runtime | To confirm by the owner |
| `react`, `react-dom` | 19.3.0, 19.3.0 | runtime (frontend) | |
| `@types/react`, `@types/react-dom` | 19.3.0, 19.3.0 | dev (frontend) | |
| `vite`, `@vitejs/plugin-react`, `vitest` | 8.3.4, 6.1.2, 5.0.3 | dev (frontend) | |
| `typescript`, `@biomejs/biome` | 6.0.3, 2.5.15 | dev (frontend) | |

## Counts

- Backend runtime: 22 new direct entries (17 PyPI packages + 4 spaCy model wheels + 1 security constraint; on 3 Nov 2026 three spaCy models removed and `gliner`, `torch`, `transformers`, `protobuf` added), 1 moved
  from dev (`jsonschema`), 1 declared directly (`opentelemetry-api`); dev: 1 removed (`httpx`). About 60 new
  transitive packages, of which ~25 come from spaCy and ~17 from the five LLM SDKs.
- Frontend: 4 runtime, 6 dev.
- Agent pack: 2 runtime + 3 dev (reused versions). Dev container: 1 base image + 3 features + uv image. CI: 3 actions.
- Pre-1.0 direct packages, audited above: `protego`, `perplexityai`, `openapi-fetch`. Security exceptions: `pypdf`
  6.21.2, `pillow` 13.0.0, `undici` ≥ 8.12.2 (transitive, dev).
