#!/usr/bin/env bash
# Deploy Supplier iScan to Google Cloud Run (#52). Called by the GitHub workflows; also usable by hand.
#
#   deploy/deploy.sh ENV images     print the image references now running in ENV (dev), for promotion
#   deploy/deploy.sh ENV migrate    apply the database migrations (a Cloud Run job, run and awaited)
#   deploy/deploy.sh ENV deploy     deploy API, worker and frontend, check /health, then send traffic
#   deploy/deploy.sh ENV health     check the API and the frontend of ENV
#
# ENV is dev or prod. Settings come from the environment (names only; the workflows read them from
# GitHub variables), never from a file with a secret:
#   GCP_PROJECT_ID, GCP_REGION                    where
#   IMAGE_API, IMAGE_WEB, IMAGE_COLLECTOR         images, pinned by digest (name@sha256:...)
#   CRAWLER_CONTACT_URL                           public contact page named in the crawler's User-Agent
#   WEB_ORIGIN, API_BASE_URL                      optional: the public addresses when a custom domain
#                                                 is used; default: the run.app addresses
#   EUR_PER_USD                                   optional: EUR for 1 USD, for costs in EUR
# Secrets are referenced by NAME from Secret Manager (iscan-ENV-<name>, see the owner guide); this
# script never reads a secret value. Sizing: deploy/env/ENV.conf; container settings: deploy/env/ENV.yaml.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
env_name="${1:-}"
action="${2:-}"
case "$env_name" in dev | prod) ;; *) echo "usage: deploy.sh dev|prod images|migrate|deploy|health" >&2; exit 2 ;; esac

need() { for name in "$@"; do [ -n "${!name:-}" ] || { echo "Missing setting: $name" >&2; exit 2; }; done; }
need GCP_PROJECT_ID GCP_REGION

# shellcheck disable=SC1090
source "$here/env/$env_name.conf"
runtime_sa="iscan-runtime@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
web_sa="iscan-web@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
api_service="iscan-api-$env_name"
web_service="iscan-web-$env_name"
worker_pool="iscan-worker-$env_name"
migrate_job="iscan-migrate-$env_name"
gc=(gcloud --project "$GCP_PROJECT_ID" --quiet)
# GIT_SHA (set by the dev workflow) is recorded on the services, so that a promotion uses the scripts
# and settings of the commit that produced the images.
labels="app=iscan,env=$env_name${GIT_SHA:+,commit=$GIT_SHA}"

secret_exists() { "${gc[@]}" secrets describe "iscan-$env_name-$1" > /dev/null 2>&1; }

# The public addresses. Cloud Run gives every service a stable address built from the project number.
project_number() { "${gc[@]}" projects describe "$GCP_PROJECT_ID" --format='value(projectNumber)'; }
run_app_url() { echo "https://$1-$(project_number).$GCP_REGION.run.app"; }

service_json() { "${gc[@]}" run services describe "$1" --region "$GCP_REGION" --format=json; }

# GET /health must answer 200 with the API and the database available. Retries cover a cold start.
# Prints the names of the missing provider settings (names only), which are not a failure.
check_api() {
  local base="$1" attempt body
  for attempt in $(seq 1 20); do
    if body="$(curl --silent --fail --max-time 30 "$base/health")"; then
      if python3 -c '
import json, sys
health = json.loads(sys.argv[1])
if health.get("api") != "available" or health.get("database") != "available":
    sys.exit(1)
missing = health.get("missing_settings", [])
print("Health: api and database available" + ("; settings not set: " + ", ".join(missing) if missing else ""))
' "$body"; then
        return 0
      fi
    fi
    echo "Health check attempt $attempt did not pass; waiting"
    sleep 15
  done
  return 1
}

case "$action" in
images)
  # Reads what is running, so that production gets exactly the images that were tested in dev.
  api_json="$(service_json "iscan-api-dev")"
  web_json="$(service_json "iscan-web-dev")"
  python3 - "$api_json" "$web_json" <<'PY'
import json
import re
import sys

api_service = json.loads(sys.argv[1])
web_service = json.loads(sys.argv[2])
api = api_service["spec"]["template"]["spec"]["containers"]
web = web_service["spec"]["template"]["spec"]["containers"]
by_name = {c["name"]: c["image"] for c in api}
images = {
    "IMAGE_API": by_name.get("api"),
    "IMAGE_COLLECTOR": by_name.get("collector"),
    "IMAGE_WEB": web[0]["image"],
}
for name, image in images.items():
    if not image or "@sha256:" not in image:
        sys.exit(f"{name} in dev is not pinned by digest: {image}")
    print(f"{name}={image}")
sha = api_service.get("metadata", {}).get("labels", {}).get("commit", "")
if not re.fullmatch(r"[0-9a-f]{40}", sha):
    sys.exit("the dev API service has no commit label: deploy to dev first")
print(f"GIT_SHA={sha}")
PY
  ;;

migrate)
  need IMAGE_API
  secret_exists database-url || { echo "Secret iscan-$env_name-database-url does not exist" >&2; exit 1; }
  "${gc[@]}" run jobs deploy "$migrate_job" --region "$GCP_REGION" --image "$IMAGE_API" \
    --service-account "$runtime_sa" --command /opt/venv/bin/python --args="-m,app.migrate" \
    --set-secrets "DATABASE_URL=iscan-$env_name-database-url:latest" \
    --cpu 1 --memory 1Gi --max-retries 0 --task-timeout 1800 --labels "$labels"
  "${gc[@]}" run jobs execute "$migrate_job" --region "$GCP_REGION" --wait
  ;;

deploy)
  need IMAGE_API IMAGE_WEB IMAGE_COLLECTOR CRAWLER_CONTACT_URL
  web_origin="${WEB_ORIGIN:-$(run_app_url "$web_service")}"
  api_url="${API_BASE_URL:-$(run_app_url "$api_service")}"
  work="$(mktemp -d)"
  trap 'rm -rf "$work"' EXIT

  # Container settings: the committed file, plus the values that differ by deployment.
  # Secrets that are files (private content) are mounted from Secret Manager; their paths are settings.
  cp "$here/env/$env_name.yaml" "$work/app.yaml"
  {
    echo "CRAWLER_CONTACT_URL: \"$CRAWLER_CONTACT_URL\""
    echo "CORS_ALLOWED_ORIGINS: \"$web_origin\""
    # The conversion rate used for costs in EUR (needed when a USD-priced provider is selected).
    [ -z "${EUR_PER_USD:-}" ] || echo "EUR_PER_USD: \"$EUR_PER_USD\""
  } >> "$work/app.yaml"

  # Secrets by name. Required ones must exist; the others are passed on when they exist.
  base_secrets="DATABASE_URL=iscan-$env_name-database-url:latest"
  api_secrets="$base_secrets,ADMIN_EMAIL=iscan-$env_name-admin-email:latest,ADMIN_PASSWORD=iscan-$env_name-admin-password:latest"
  for required in database-url admin-email admin-password; do
    secret_exists "$required" || { echo "Secret iscan-$env_name-$required does not exist" >&2; exit 1; }
  done
  extra=""
  for pair in ANTHROPIC_API_KEY:anthropic-api-key GEMINI_API_KEY:gemini-api-key OPENAI_API_KEY:openai-api-key \
    MISTRAL_API_KEY:mistral-api-key PERPLEXITY_API_KEY:perplexity-api-key; do
    if secret_exists "${pair#*:}"; then extra="$extra,${pair%%:*}=iscan-$env_name-${pair#*:}:latest"; fi
  done
  for pair in PROVIDER_CONFIG_FILE:provider-config PRICE_TABLE_FILE:price-table PROFILE_DEFINITION_FILE:profile-definition \
    PROMPT_SET_FILE:prompt-set COUNTRY_TABLE_FILE:country-table PDF_DISCLAIMER_FILE:pdf-disclaimer; do
    if secret_exists "${pair#*:}"; then
      mount="/secrets/${pair#*:}/content.json"
      extra="$extra,$mount=iscan-$env_name-${pair#*:}:latest"
      echo "${pair%%:*}: \"$mount\"" >> "$work/app.yaml"
    fi
  done

  # --- API (with the telemetry sidecar). The new revision gets no traffic until /health passes. ---
  "${gc[@]}" run deploy "$api_service" --region "$GCP_REGION" \
    --service-account "$runtime_sa" --allow-unauthenticated \
    --min-instances "$API_MIN_INSTANCES" --max-instances "$API_MAX_INSTANCES" \
    --concurrency "$API_CONCURRENCY" --timeout "$API_TIMEOUT_SECONDS" --cpu-boost \
    --no-traffic --tag candidate --labels "$labels" \
    --container api --image "$IMAGE_API" --port 8000 --cpu "$API_CPU" --memory "$API_MEMORY" \
    --env-vars-file "$work/app.yaml" --set-secrets "$api_secrets$extra" \
    --container collector --image "$IMAGE_COLLECTOR" --cpu "$COLLECTOR_CPU" --memory "$COLLECTOR_MEMORY"

  candidate="$(service_json "$api_service" | python3 -c '
import json, sys
for t in json.load(sys.stdin).get("status", {}).get("traffic", []):
    if t.get("tag") == "candidate":
        print(t["url"])
')"
  [ -n "$candidate" ] || { echo "The candidate revision has no address" >&2; exit 1; }
  check_api "$candidate" || { echo "The new API revision failed its health check; traffic was not moved." >&2; exit 1; }
  "${gc[@]}" run services update-traffic "$api_service" --region "$GCP_REGION" --to-latest --remove-tags candidate

  # --- Frontend. One image for every environment; the API address is set here, at run time. ---
  "${gc[@]}" run deploy "$web_service" --region "$GCP_REGION" \
    --image "$IMAGE_WEB" --port 8080 --service-account "$web_sa" --allow-unauthenticated \
    --cpu "$WEB_CPU" --memory "$WEB_MEMORY" --min-instances 0 --max-instances "$WEB_MAX_INSTANCES" \
    --set-env-vars "API_BASE_URL=$api_url" --labels "$labels"

  # --- Worker: a Cloud Run worker pool (no HTTP port, runs continuously). See cloud-run-sizing.md. ---
  if [ "$WORKER_INSTANCES" -gt 0 ] || "${gc[@]}" beta run worker-pools describe "$worker_pool" --region "$GCP_REGION" > /dev/null 2>&1; then
    "${gc[@]}" beta run worker-pools deploy "$worker_pool" --region "$GCP_REGION" \
      --service-account "$runtime_sa" --instances "$WORKER_INSTANCES" --labels "$labels" \
      --container worker --image "$IMAGE_API" --command /opt/venv/bin/python --args="-m,app.worker" \
      --cpu "$WORKER_CPU" --memory "$WORKER_MEMORY" \
      --env-vars-file "$work/app.yaml" --set-secrets "$base_secrets$extra" \
      --container collector --image "$IMAGE_COLLECTOR" --cpu "$COLLECTOR_CPU" --memory "$COLLECTOR_MEMORY"
  else
    echo "Worker for $env_name is switched off (WORKER_INSTANCES=0) and does not exist: nothing deployed."
  fi
  ;;

health)
  check_api "$(service_json "$api_service" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"]["url"])')"
  web="$(service_json "$web_service" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"]["url"])')"
  curl --silent --show-error --fail --max-time 30 "$web/" > /dev/null
  echo "Frontend answers at $web"
  ;;

*)
  echo "usage: deploy.sh dev|prod images|migrate|deploy|health" >&2
  exit 2
  ;;
esac
