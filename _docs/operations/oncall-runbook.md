# On-call runbook: failure-rate alert and on-call agent (dev)

Issue #53. **Dev only**: production alerting and an agent identity that starts CI on its own pull requests are
follow-up #165.

## How it works

```
profile runs fail ──► metric iscan_runs_finished_total (Cloud Monitoring, PromQL)
                      │
                      ▼
alert policy "iscan-dev profile-run failure rate"   (deploy/monitoring/failure-rate.dev.json)
   failed / finished runs over 15 min > 0.5, at least 3 runs finished, held 5 min
   │                                   │
   ▼                                   ▼
email to the owner            webhook (basic auth) ──► Cloud Run iscan-alert-relay (deploy/alert-relay)
                                                        │  open incident only; 401 / 400 otherwise
                                                        ▼
                               GitHub workflow_dispatch of .github/workflows/oncall.yml on main
                                  triage  ─► one incident, one issue; cooldown 60 min (flapping)
                                  collect ─► telemetry with iscan-oncall-reader (read-only, no LLM)
                                  agent   ─► Claude Code, data in, report.json out (no cloud credential)
                                  report  ─► issue labelled `incident`; fix on oncall/<id> + pull request
```

The agent **never** merges, deploys or pushes to main (`deploy/check_workflows.py` enforces it on `oncall.yml`).
The email does not depend on the relay or the agent: it always arrives.

Values (owner-approved, 11 Nov 2026), all in `deploy/monitoring/failure-rate.dev.json`: threshold 0.5, window
15 min, at least 3 finished runs, held 5 min, auto-close 30 min. Cooldown: repository variable
`ONCALL_COOLDOWN_MINUTES` (60 when unset).

## Set-up (owner, once, in this order)

Open Cloud Shell and paste the name block of the owner guide, step 3 (`PROJECT_ID`, `REGION`, `GITHUB_REPO`,
`PROJECT_NUMBER`). The commands below never print a secret value. The relay and the drill switch need this pull
request merged and deployed to dev first (the deploy writes `DEPLOYMENT_ENVIRONMENT=dev`).

### 1. Repository settings (approval 5)

- GitHub, the repository, **Settings**, **Actions**, **General**, *Workflow permissions*: tick **Allow GitHub
  Actions to create and approve pull requests**. Save.
- The label (from any terminal with `gh`):

  ```sh
  gh label create incident -R "$GITHUB_REPO" --color B60205 --description "On-call incident (#53)"
  ```

### 2. The model key (approval 2)

Set a monthly spending limit on the Anthropic console first. Then:

```sh
gh secret set ONCALL_ANTHROPIC_API_KEY --env oncall -R "$GITHUB_REPO"
```

`gh` asks for the value (paste it; it is not echoed). It needs the environment `oncall` to exist first
(`gh` does not create it): **Settings**, **Environments**, **New environment** `oncall`, then *Deployment branches
and tags*: **Selected branches**, add `main`.

### 3. The read-only account (approval 3)

```sh
gcloud iam service-accounts create iscan-oncall-reader --display-name="iScan on-call reader (GitHub, read-only)"
READER_SA="iscan-oncall-reader@${PROJECT_ID}.iam.gserviceaccount.com"
for role in roles/logging.viewer roles/cloudtrace.user roles/monitoring.viewer; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$READER_SA" --role="$role" \
    --condition=None --quiet > /dev/null
done

# The GitHub sign-in also carries the workflow file; map it (the existing mappings are kept).
gcloud iam workload-identity-pools providers update-oidc github-actions --location=global \
  --workload-identity-pool=github \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref,attribute.workflow_ref=assertion.workflow_ref"

# Only oncall.yml of this repository, on main, may act as the reader.
gcloud iam service-accounts add-iam-policy-binding "$READER_SA" --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/attribute.workflow_ref/${GITHUB_REPO}/.github/workflows/oncall.yml@refs/heads/main"

gh variable set ONCALL_READER_SERVICE_ACCOUNT -R "$GITHUB_REPO" --body "$READER_SA"
```

No key file exists. If Google refuses the `principalSet` above, check the claim in a run log of `oncall.yml`
(`workflow_ref`) and use exactly that value.

### 4. The relay and its two secrets (approval 4)

The GitHub token: GitHub, your avatar, **Settings**, **Developer settings**, **Personal access tokens**,
**Fine-grained tokens**, **Generate new token**. Name `iscan-dev-alert-relay`; **expiration** 90 days (write the
date in your calendar); **Repository access**: only this repository; **Permissions**: *Actions*: **Read and
write**, nothing else. Copy it once, then:

```sh
# the token you just copied: paste it, press Enter, then Ctrl-D
gcloud secrets create iscan-dev-github-dispatch-token --replication-policy=automatic --data-file=-
# a random password for the webhook, generated and stored without being shown
python3 -c 'import secrets; print(secrets.token_urlsafe(32), end="")' | \
  gcloud secrets create iscan-dev-alert-webhook-token --replication-policy=automatic --data-file=-

gcloud iam service-accounts create iscan-alert-relay --display-name="iScan alert relay"
RELAY_SA="iscan-alert-relay@${PROJECT_ID}.iam.gserviceaccount.com"
for secret in iscan-dev-alert-webhook-token iscan-dev-github-dispatch-token; do
  gcloud secrets add-iam-policy-binding "$secret" --member="serviceAccount:$RELAY_SA" \
    --role=roles/secretmanager.secretAccessor --quiet > /dev/null
done

# Build the relay image (standard library only), push it, deploy it pinned by digest.
git clone "https://github.com/${GITHUB_REPO}.git" iscan-relay-src && cd iscan-relay-src
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/iscan/alert-relay:$(git rev-parse HEAD)"
docker build --tag "$IMAGE" deploy/alert-relay && docker push "$IMAGE"
IMAGE_RELAY="$(docker inspect --format '{{index .RepoDigests 0}}' "$IMAGE")"
GCP_PROJECT_ID="$PROJECT_ID" GCP_REGION="$REGION" GITHUB_REPOSITORY="$GITHUB_REPO" IMAGE_RELAY="$IMAGE_RELAY" \
  deploy/deploy.sh dev relay
cd ..
```

*Expect* "Relay address (URL of the webhook channel): https://iscan-alert-relay-...run.app/". A request without the
password gets 401: `curl -s -o /dev/null -w '%{http_code}\n' -X POST "$(gcloud run services describe iscan-alert-relay --region "$REGION" --format='value(status.url)')/"`
prints `401`.

### 5. The two notification channels (approval 6)

```sh
# your email: typed here, stored in Cloud Monitoring only (never in the repository)
gcloud beta monitoring channels create --display-name=iscan-dev-email --type=email \
  --channel-labels=email_address=YOUR-EMAIL

RELAY_URL="$(gcloud run services describe iscan-alert-relay --region "$REGION" --format='value(status.url)')/"
gcloud beta monitoring channels create --display-name=iscan-dev-alert-relay --type=webhook_basicauth \
  --channel-labels="url=${RELAY_URL},username=cloud-monitoring,password=$(gcloud secrets versions access latest --secret=iscan-dev-alert-webhook-token)"
```

Cloud Monitoring sends a verification email for the email channel: click its link.

### 6. The alert policy

```sh
cd iscan-relay-src && git pull
GCP_PROJECT_ID="$PROJECT_ID" make alert-apply ENV=dev
```

*Expect* `Alert policy 'iscan-dev profile-run failure rate': created` (and `updated ...` when run again: there is
always one policy). The command fails, naming the channel, if a channel of step 5 is missing. To check:
Monitoring, **Alerting**, the policy shows the PromQL condition and the two channels.

> **Known limitation (dev):** Cloud Run worker pools do not support secret volume mounts yet, so the deploy gives
> the worker the keys but not the private content files; a real profile run on the hosted dev instance uses the
> shipped example content. The drill is not affected (its runs fail at the start of collection).

## The drill (live, dev)

Shows the whole chain. About 30 minutes. Record each link for the pull request.

```sh
# 1. worker on, drill switch on (only the dev worker; dev accepts it, prod refuses it)
gcloud beta run worker-pools update iscan-worker-dev --region="$REGION" --instances=1
gcloud beta run worker-pools update iscan-worker-dev --region="$REGION" --container=worker \
  --update-env-vars=FAULT_INJECTION_FAIL_RUNS=true
```

2. In the dev app, start **three** profile runs (any supplier). Each fails at once at the start of collection
   with `SyntheticFaultInjected`: nothing is collected, nothing is sent to a provider, no cost.
3. Within about 5 to 10 minutes: the incident opens (Monitoring, **Alerting**), **the email arrives**, the relay
   logs `POST 204 dispatched`, and the **On-call** run starts in the Actions tab. If it does not fire, start a
   fourth run (the first run of a fresh series can be missed by `increase`).
4. When the run ends: the issue labelled `incident` holds the diagnosis (expected: the synthetic error, component
   `collection`, proposed change `none`).

```sh
# 5. drill switch off, worker off
gcloud beta run worker-pools update iscan-worker-dev --region="$REGION" --container=worker \
  --remove-env-vars=FAULT_INJECTION_FAIL_RUNS
gcloud beta run worker-pools update iscan-worker-dev --region="$REGION" --instances=0
```

The incident closes by itself once fewer than 3 runs finished in the window (the email says so); the relay ignores
the closed notification. Any later dev deployment also resets the switch to `"false"` (`deploy/env/dev.yaml`).

## The replay (evaluation case, no cloud needed)

Actions, **On-call**, **Run workflow** (branch `main`), fields:

| Field | Value |
| :--- | :--- |
| incident_id | `replay-provider-error-1` (a new value per replay) |
| policy_name | `replay provider-error` (not the real policy, so the cooldown does not merge it with a drill) |
| environment | `dev` |
| started_at | `2026-11-12T10:00:00Z` |
| console_url | empty |
| fixture | `provider-error` |

The telemetry comes from `ops/oncall/fixtures/provider-error.json` (runs failing in extraction on
`StructuredOutputInvalid`). **Pass:** the issue names `StructuredOutputInvalid` and the component `extraction` (or
`providers`). The run needs the key only (step 2), not the reader account. The same form, with the fields of a
real incident and `fixture` empty, is the **manual fallback** when the relay is down: it behaves exactly as the
relay's dispatch.

## By hand (the agent failed, or is off)

The issue says which step failed (triage, telemetry collection, agent, report validation). In any case:

1. Open the incident from the email (Monitoring, **Alerting**). Is the failure rate still high?
2. Stop the damage if needed: switch the dev worker off (`--instances=0`, owner guide step 17).
3. Logs Explorer, this query, last hour:
   `jsonPayload.level=("ERROR" OR "WARNING") AND (resource.labels.service_name="iscan-api-dev" OR resource.labels.worker_pool_name="iscan-worker-dev")`.
   Read `error_type` and `error_stack`; copy a `trace_id`.
4. **Trace**, paste the trace ID: which stage and which provider call failed.
5. Fix in a normal issue and pull request.

Common causes of an on-call failure:

| Message in the issue | Fix |
| :--- | :--- |
| `missing reader configuration ...` | Step 3 (repository variable `ONCALL_READER_SERVICE_ACCOUNT`, or `GCP_PROJECT_ID`) |
| `ONCALL_ANTHROPIC_API_KEY is not set` | Step 2 |
| `model error, turn limit or timeout` | Check the provider status and the spending limit; re-run the replay |
| `report failed validation` | The agent's answer broke the schema; the rules broken are listed; handle by hand |

**No On-call run at all although the email arrived:** the relay could not dispatch. Its log:

```sh
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="iscan-alert-relay"' \
  --limit=10 --format='value(timestamp,textPayload)'
```

`POST 502 GitHub answered 401` means the GitHub token **expired** or was revoked: create a new one (step 4), then
`gcloud secrets versions add iscan-dev-github-dispatch-token --data-file=-` (paste, Enter, Ctrl-D) and deploy the
relay again (the `deploy/deploy.sh dev relay` command of step 4). Meanwhile, use the manual fallback above.

## Switch the agent off

- Agent only (email kept): `gh workflow disable oncall.yml -R "$GITHUB_REPO"` (undo: `gh workflow enable`). The
  relay then logs `POST 502 GitHub answered 422`; nothing else happens.
- Relay off: `gcloud run services delete iscan-alert-relay --region="$REGION"` (the webhook then fails; the email
  still arrives). Or remove `iscan-dev-alert-relay` from `channels` in `failure-rate.dev.json` and run
  `make alert-apply ENV=dev`.
- Everything: `gcloud beta monitoring policies list --filter='displayName="iscan-dev profile-run failure rate"' --format='value(name)'`,
  then `gcloud beta monitoring policies delete NAME`.
