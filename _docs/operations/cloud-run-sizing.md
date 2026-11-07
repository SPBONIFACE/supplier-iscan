# Cloud Run sizing, worker choice and telemetry (#52)

Reasoning behind `deploy/env/*.conf` and `deploy/env/*.yaml`. Settings are by name; values are in those files.
Everything here is a proposal that the first real deployment confirms or corrects: figures marked *to confirm*
cannot be known before then.

## What the numbers come from

- The name-detection model (GLiNER) loads lazily in each process that redacts text, about 1.2 GB resident, first
  load 25 to 140 s (laptop CPU). The API and the worker each load their own copy.
- The backend image is about 1.77 GB (model and PDF libraries included). One image serves API, worker and the
  migration job.
- A card PDF takes about 3 s and 150 MB. Redaction of 100 kB of text took 67 to 90 s on 4 threads
  (`REDACTION_THREADS`, default 4).
- The `images` CI workflow runs the model inside the built image with a 4 GB memory limit and 2 CPUs, offline
  (`--network none`), and prints the load time and the peak memory in its summary. **Measured on the GitHub runner
  (6 Nov 2026, PR #128, 2 CPUs, 7.9 GB): the model loads in 7.9 s (11.0 s in the first run), a first short
  redaction takes 0.3 s, 12.3 kB of text takes 25 s, the process peaks at 2.9 GB (container 2.9 GB) under the 4 GB
  limit; the image is 3.0 GB uncompressed after `uv sync --no-cache`.** So the model does run
  in the built image, in the memory proposed here, with about 1 GB of headroom; if Cloud Run reports memory
  kills, raise the memory to 6 GiB first. (The earlier failure to finish was the 4 GB Docker VM shared with other
  containers, not the image.)

## Services

| | API | Worker | Frontend | Telemetry sidecar |
|---|---|---|---|---|
| Kind | Cloud Run service | Cloud Run worker pool | Cloud Run service | container in the API and the worker |
| CPU / memory | 2 / 4 GiB | 4 / 4 GiB | 1 / 256 MiB | 1 / 512 MiB |
| Instances | 0 to 2 (dev), 0 to 3 (prod) | 0 (dev, switched off), 1 (prod) | 0 to 2 / 3 | with its host |
| Concurrency | 8 | not applicable | default (80) | |
| Request timeout | 300 s | not applicable | default | |

- **Memory 4 GiB** for API and worker: the model (1.2 GB) plus PyTorch buffers, Python, the PDF renderer (150 MB)
  and headroom for a long text. 2 GiB would be killed (measured peak 2.9 GB); 8 GiB buys nothing known. *To
  confirm* on the first real run with a long text and several requests at once.
- **CPU**: redaction is CPU-bound and runs on 4 threads, so the worker gets 4 vCPU. The API gets 2: it redacts
  only short texts in the request path (identity, review), and calls to the model are serialised by a lock.
- **Concurrency 8** on the API: requests are mostly waiting for the database. The model lock means two long
  redactions in one instance queue; a second instance starts when the 8 are used.
- **Scale to zero** for the API and the frontend (cost). The price: after a pause the first request waits for the
  start (image pull of 1.77 GB, then the lazy model load on first redaction: 25 to 140 s). `--cpu-boost` shortens
  the start. For production, `API_MIN_INSTANCES=1` removes the start wait; it does not remove the model load.
- **Request timeout 300 s** (the default): covers a first model load inside a request. Long work is never in a
  request; it is a run in the worker.
- **Startup**: the API stays lazy (it must answer `/health` in seconds, and a 140 s load at start would exceed
  Cloud Run's startup probe patience on a small instance). For the **worker**, loading the model at start,
  before the first job is claimed, is recommended: the first buyer then does not wait while a database row is
  locked (the owner's question on #19). That is a code change in `app/worker.py` (call the redactor's `load()`
  before the polling loop), not made in this task: open a follow-up issue.

## Worker: worker pool, not service, not job

The worker is a polling loop with no HTTP port that must run continuously and works for minutes per run.

- A Cloud Run **service** needs an HTTP port and a request to keep its CPU; a loop with no request is throttled
  to near zero CPU, and Cloud Run stops an instance with no traffic. It would need a code change (a health
  listener) and always-on CPU billing anyway.
- A Cloud Run **job** runs to completion and then ends. It fits if the API triggered one job execution per run
  (scale to zero, exact cost), but that needs the API to call the Cloud Run Jobs API and a different queue
  design: a change of architecture, not a deployment task.
- A Cloud Run **worker pool** is made for this: a continuous container without an HTTP endpoint, a fixed number
  of instances, no request needed. Its cost is the price of the instance while it runs.
  The worker is **off by default in dev and in production**: `deploy/deploy.sh` creates the pool with zero
  instances and never changes the count of an existing pool; the owner switches it on for a run or a demo and off
  afterwards (guide, step 17). With no worker, a started run waits in the queue (the screen says it is waiting to start). Worker pools are a recent Cloud Run feature (the `gcloud beta run worker-pools` command): *to
  confirm* at the first deploy that the command and the region support it. Fallback if not: a service with
  `--no-cpu-throttling --min-instances 1` and a minimal health listener (follow-up code change).
- The worker polls the database (`WORKER_POLL_SECONDS`, 5 s here), so a production Neon compute never goes idle
  while the worker runs. Plan for that in Neon's compute hours (see the owner guide), or accept the cost.

## Settings by name

Set per environment in `deploy/env/*.yaml` (non-secret) and from GitHub environment variables (values that differ):

| Name | Where | Meaning |
|---|---|---|
| `INSTANCE_MODE` | yaml | `hosted` |
| `RUN_BUDGET_EUR` | yaml | per-run cost budget, API and worker refuse to start without it |
| `COLLECT_MAX_REQUESTS`, `COLLECT_MAX_DOMAINS` | yaml | ceilings per run: 200 and 10 |
| `CRAWLER_CONTACT_URL` | GitHub environment variable | public contact page named in the crawler's User-Agent; the worker refuses to start without it |
| `CORS_ALLOWED_ORIGINS` | computed | exactly the frontend's address of that environment (its run.app address) |
| `EUR_PER_USD` | GitHub environment variable | conversion rate for costs |
| `OTEL_EXPORTER_OTLP_ENDPOINT`, `TELEMETRY_EXPORT_TIMEOUT_SECONDS`, `DATABASE_STATEMENT_TIMEOUT_SECONDS` | yaml | telemetry and database timeouts |
| `RUN_LEASE_SECONDS`, `WORKER_POLL_SECONDS` | yaml | job queue |
| `PROVIDER_CONFIG_FILE`, `PRICE_TABLE_FILE`, `PROFILE_DEFINITION_FILE`, `PROMPT_SET_FILE`, `COUNTRY_TABLE_FILE`, `PDF_DISCLAIMER_FILE` | computed | paths of files mounted from Secret Manager at run time, when the secret exists (`/secrets/<name>/content.json`) |
| `API_UPSTREAM_URL` | computed (frontend) | address of the API service; the frontend's nginx forwards `/api/` to it (below) |

Not set (defaults apply): `INVITATION_VALIDITY_HOURS` (72), `PASSWORD_MIN_LENGTH` (12), `MONTHLY_SPEND_CAP_EUR`
(no cap: the owner may want one; add it to the yaml), `REDACTION_THREADS` (4), PDF limits (no cap on rendering
time or size exists in the code; the 4 GiB limit and the 300 s timeout are the only bounds. Follow-up: an explicit
cap).

Secrets, by name, in Secret Manager as `iscan-<env>-<name>`: `database-url`, `admin-email`, `admin-password`
(required), `anthropic-api-key`, `gemini-api-key`, `openai-api-key`, `mistral-api-key`, `perplexity-api-key`
(each passed on when it exists), and the file secrets `provider-config`, `price-table`, `profile-definition`,
`prompt-set`, `country-table`, `pdf-disclaimer`.

## One address: the frontend forwards `/api/` to the API

The session cookie is `SameSite=Lax; Secure; HttpOnly`. Two `*.run.app` addresses are different sites (`run.app`
is on the public suffix list), so a browser calling the API at its own address would not send the cookie. The
decision (owner, 7 Nov 2026): **no custom domain**. The browser talks to the frontend service only, with relative
addresses (`/api/...`); the frontend's nginx (`frontend/deploy/nginx.conf.template`) forwards them to the API service.
The cookie is set by an answer that comes through the frontend's address, so it belongs to that one site.

- **Prefix**: nginx removes `/api`; the API still serves at its root (`/health`, `/runs`, ...), so `openapi.yaml` is
  unchanged. The frontend's API base is `/api` (set when the image is built, the same in every environment).
- **Upstream**: `API_UPSTREAM_URL` is set at run time by `deploy/deploy.sh` (the API's run.app address); the image
  has no address in it, and refuses to start if it is missing, not `https://`, or not a plain address.
  nginx connects over HTTPS (`proxy_ssl_server_name on`, `Host` and the TLS name set to the upstream's host) and
  looks the name up again every 30 s (the platform's resolver).
- **Timeouts**: connect 10 s, send 60 s, read 330 s: longer than the API's own 300 s limit, so the API answers (or
  Cloud Run ends the request) before nginx gives up; the slowest call is the PDF. Body limit 256 KB (the API
  accepts short JSON bodies; its longest text field is 2000 characters).
- **Client address**: the application does not read the client's IP address anywhere (no rate limit or quota is
  per address: limits are per organisation, per run and per domain crawled), and uvicorn ignores `X-Forwarded-*`
  from any sender other than 127.0.0.1. Nothing therefore trusts those headers, which is the safe choice: a
  caller cannot forge an address, because none is used. Cloud Run's front end adds the real client to
  `X-Forwarded-For`, nginx appends its own peer address and passes it with `X-Forwarded-Proto`, so a later feature
  that needs the client (a login rate limit) can take the first entry written by Cloud Run, trusting exactly two
  hops (Cloud Run's front end, then nginx), and only that. Until then, do not add `--forwarded-allow-ips`.
- **Logs**: the access line is `METHOD /path status bytes seconds upstream-status`. Never the query string, a
  cookie or any header; the invitation token in `/api/invitations/<token>` is replaced by `[redacted]`. nginx's
  error log is limited to critical errors, because its lines quote the whole request line, query string included;
  an unreachable API shows as 502 or 504 in the access log and in the API's own logs.
- **CORS**: the browser's calls are same-origin, so CORS is not needed any more. It stays, narrowed to the one
  exact frontend address (no wildcard, no localhost default in a deployed environment), as a harmless safeguard;
  it can be removed in a later change without effect on users.
- **API address**: the API service stays public (`--allow-unauthenticated`, as the frontend's nginx calls it with
  no Google identity). Someone who knows its address can call it directly: every protected call still needs the
  session cookie, which that address never receives from the browser. Closing it (Google identity tokens between
  the two services) is a possible hardening, not done here.

Tools approved by the owner, 7 Nov 2026: `google-github-actions/auth` v3.0.0, `google-github-actions/setup-gcloud`
v3.0.1, Google Cloud CLI 592.0.0, `nginxinc/nginx-unprivileged` 1.29.3-alpine (digest pinned), `otelcol-google`
(digest pinned).

## Telemetry: Google Cloud's own

Choice: **Cloud Trace** for traces and **Cloud Monitoring (Managed Service for Prometheus)** for metrics, fed by
the Google-built OpenTelemetry Collector as a **sidecar** in each API instance and worker instance
(`deploy/collector`). Logs: Cloud Run sends the JSON lines on standard error to **Cloud Logging** with no setup.

Why: no new account (same project and billing), no key (the sidecar uses the instance's service account), email
alerts through Cloud Monitoring notification channels (#53), and the metrics are queryable with PromQL, which is
what `README.md` already documents for the failure-rate alert. The application only needs
`OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`; the application cannot talk to Google's own OTLP endpoint
directly because that needs a short-lived Google token, not the static header the SDK setting allows.

Values: `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`, `TELEMETRY_EXPORT_TIMEOUT_SECONDS=5`. The runtime
service account needs `roles/cloudtrace.agent`, `roles/monitoring.metricWriter` and `roles/logging.logWriter`
(owner guide). Self-hosters keep using any OTLP collector; export stays off when the endpoint is empty.

Notes to confirm at the first deploy: (1) the sidecar's resource labels for the Prometheus metrics (a PromQL query
may need a label such as `job`); (2) Cloud Logging reads `severity`, while the application logs `level`, so the
log entries show as default severity until the log format gains a `severity` field (follow-up, with #53);
(3) the CPU split: API 2 + sidecar 1 = 3 vCPU, which Cloud Run may require rounding for the instance.
