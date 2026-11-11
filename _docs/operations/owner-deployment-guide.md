# Owner guide: setting up the hosted Supplier iScan (Google Cloud and Neon)

For the person who owns the project, not a developer. You do this once. Until you finish, the automatic
deployment does nothing (it prints "Deployment skipped" and stays green), so nothing breaks while you set up.

**What you will have at the end.** Two environments, **dev** (for trying changes) and **production**. Every time a
change is merged, GitHub builds the application and puts it in dev by itself. Production only changes when you
press a button and approve. The database lives at Neon (EU). The application runs at Google Cloud Run (EU). No
password or key is ever stored in GitHub or in a file: they stay in Google Secret Manager.

**Time and money.** About 2 hours the first time. Cost stays small while nobody uses it: Cloud Run scales to zero,
Neon scales to zero. A budget alert (step 2) warns you by email if the bill grows. The one thing that costs
continuously is the worker, and it is **off** until you switch it on (step 17).

**Words you will meet.** *Project*: your box in Google Cloud. *Cloud Shell*: a terminal that runs in your web
browser, with Google's tools already installed (nothing to install on your computer). *Secret Manager*: Google's
safe for passwords. *Service account*: a robot identity with only the permissions you give it. *Workload Identity
Federation*: lets GitHub prove "I am this repository" to Google without any password.

**Rules for yourself.** Never paste a password, a key or a database address into a chat, an email, an issue or a
file. The steps below type them into a hidden prompt, straight into Secret Manager.

Text in `code blocks` is copied as it is, one block at a time, into Cloud Shell, unless a step says otherwise.
Words in CAPITALS inside a block are yours to replace.

---

## Part A. Google Cloud

### 1. Create the project and link billing

1. Go to <https://console.cloud.google.com> and sign in with the Google account that will own this.
2. Top bar, project picker, **New project**. Name: `supplier-iscan` (you can add `-prod` later if you want two
   projects). Note the **Project ID** it shows (letters, digits, dashes; unique worldwide).
3. Menu, **Billing**. Link a billing account (a card). If you have none, create one.

*What to expect:* the project appears in the picker. Nothing is billed yet.

### 2. Set a budget alert (EUR 10)

1. Menu, **Billing**, **Budgets & alerts**, **Create budget**.
2. Name `iscan-monthly`. Scope: the project. Amount: **Specified amount, EUR 10**.
3. Alerts: keep 50%, 90%, 100%. Tick **Email alerts to billing admins and users**.
4. **Finish.**

*What to expect:* emails when spend reaches EUR 5, 9 and 10. A budget does not stop spending; it warns you.
Act on a warning (step 17 shows how to switch things off).

### 3. Open Cloud Shell and set your names

1. In the console, top right, click the **terminal icon** (Activate Cloud Shell). Wait for the prompt.
2. Paste (replace the three values; the region keeps your data in the EU, Frankfurt, next to Neon's Frankfurt):

```sh
export PROJECT_ID="YOUR-PROJECT-ID"
export REGION="europe-west3"
export GITHUB_REPO="YOUR-GITHUB-ACCOUNT/supplier-iscan"
gcloud config set project "$PROJECT_ID"
export PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
echo "Project number: $PROJECT_NUMBER"
```

*What to expect:* a number is printed. Cloud Shell forgets these names when it closes: if you come back later,
paste this block again before any other.

### 4. Turn on the Google services

```sh
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com \
  iam.googleapis.com iamcredentials.googleapis.com cloudresourcemanager.googleapis.com sts.googleapis.com \
  cloudtrace.googleapis.com monitoring.googleapis.com logging.googleapis.com telemetry.googleapis.com
```

*What it does:* switches on the services the application uses. *Expect* a minute of waiting and
"Operation finished successfully".

### 5. Create the place where images are stored (Artifact Registry)

```sh
gcloud artifacts repositories create iscan --repository-format=docker --location="$REGION" \
  --description="Supplier iScan images"
```

*What it does:* a private shelf for the application images (never public).

### 6. Create the three robot identities and give each only what it needs

```sh
# 1. runs the API, the worker and the migration job
gcloud iam service-accounts create iscan-runtime --display-name="iScan runtime"
# 2. runs the website (needs no permission at all)
gcloud iam service-accounts create iscan-web --display-name="iScan web"
# 3. used by GitHub to deploy
gcloud iam service-accounts create iscan-deployer --display-name="iScan deployer (GitHub)"

RUNTIME_SA="iscan-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
WEB_SA="iscan-web@${PROJECT_ID}.iam.gserviceaccount.com"
DEPLOY_SA="iscan-deployer@${PROJECT_ID}.iam.gserviceaccount.com"

# runtime: read secrets, write traces, metrics and logs
for role in roles/secretmanager.secretAccessor roles/cloudtrace.agent roles/monitoring.metricWriter roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$RUNTIME_SA" --role="$role" --condition=None --quiet > /dev/null
done

# deployer: deploy to Cloud Run, push images, see (not read) secrets, read the project number, set a log filter
for role in roles/run.admin roles/artifactregistry.writer roles/secretmanager.viewer roles/browser roles/logging.configWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$DEPLOY_SA" --role="$role" --condition=None --quiet > /dev/null
done
# the deployer may start services as the runtime and web robots, and nothing else
for sa in "$RUNTIME_SA" "$WEB_SA"; do
  gcloud iam service-accounts add-iam-policy-binding "$sa" --member="serviceAccount:$DEPLOY_SA" \
    --role=roles/iam.serviceAccountUser --quiet > /dev/null
done
echo "Robots ready: $DEPLOY_SA"
```

*What to expect:* "Robots ready". The deployer cannot read your secrets' contents, only see that they exist.

### 7. Let GitHub deploy without any password (Workload Identity Federation)

```sh
gcloud iam workload-identity-pools create github --location=global --display-name="GitHub Actions"

gcloud iam workload-identity-pools providers create-oidc github-actions \
  --location=global --workload-identity-pool=github \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
  --attribute-condition="assertion.repository=='${GITHUB_REPO}' && assertion.ref=='refs/heads/main'"

gcloud iam service-accounts add-iam-policy-binding "$DEPLOY_SA" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/attribute.repository/${GITHUB_REPO}"

echo "Provider (copy this for step 12):"
gcloud iam workload-identity-pools providers describe github-actions --location=global \
  --workload-identity-pool=github --format='value(name)'
```

*What it does:* tells Google "accept GitHub's sign-in only from this repository, only from its `main` branch, and
let it act as the deployer robot". There is no key to leak or to expire. *Expect* a line starting with
`projects/` followed by numbers: that is not a secret (it is an address), and you will put it into GitHub in step 12.

---

## Part B. Neon (the databases)

### 8. Recover your Neon account and create the two databases

1. Go to <https://console.neon.tech> and sign in. If you cannot remember how: use **Forgot password** with the
   email you think you used, or try each sign-in button (Google, GitHub, Microsoft). If none works, create a new
   account with a work email you control and enable two-step sign-in.
2. **New project**, name `iscan-dev`. Postgres version **16**. Region **AWS Europe (Frankfurt) eu-central-1**
   (pick another EU region only if you also change `REGION` in step 3 to a Google region nearby).
3. Repeat for a second project named `iscan-prod`, same version and region.
4. For each project, in Settings, **Compute**: leave "Scale to zero" on (cost). For `iscan-prod` you may raise
   the suspend time later if the first request after a pause feels slow.

*What to expect:* each project has one database (`neondb`) and a role. You do not need to create tables: the
application creates them.

### 9. Store each connection string in Secret Manager only

For each project in Neon: **Connect** button, choose the **direct** connection (turn OFF the "Connection pooling"
switch), copy the string that starts with `postgresql://`. **Direct, not pooled**: the application locks the
database during start and the pooled address breaks that.

Back in Cloud Shell, for dev (the prompt is hidden; paste the string and press Enter; nothing is shown):

```sh
read -rs -p "Neon DEV connection string: " NEON_URL; echo
printf '%s' "$NEON_URL" | gcloud secrets create iscan-dev-database-url --data-file=- --replication-policy=automatic
unset NEON_URL
```

Then production:

```sh
read -rs -p "Neon PROD connection string: " NEON_URL; echo
printf '%s' "$NEON_URL" | gcloud secrets create iscan-prod-database-url --data-file=- --replication-policy=automatic
unset NEON_URL
```

*What to expect:* "Created secret". The string is now only in Secret Manager. Clear your clipboard.

### 10. The first administrator and the provider keys, also only in Secret Manager

The administrator account is created the first time the application starts on an empty database. Choose an
email and a strong password (at least 12 characters). For each environment (here dev; repeat with `prod`):

```sh
ENVNAME=dev
read -r -p "Administrator email for $ENVNAME: " VALUE
printf '%s' "$VALUE" | gcloud secrets create "iscan-$ENVNAME-admin-email" --data-file=- ; unset VALUE
read -rs -p "Administrator password for $ENVNAME (hidden): " VALUE; echo
printf '%s' "$VALUE" | gcloud secrets create "iscan-$ENVNAME-admin-password" --data-file=- ; unset VALUE
```

Provider keys (any time later; a missing key is reported by the health check as a missing setting, not a crash).
The names are exactly: `anthropic-api-key`, `gemini-api-key`, `openai-api-key`, `mistral-api-key`,
`perplexity-api-key`:

```sh
ENVNAME=dev
SECRET=perplexity-api-key
read -rs -p "Key for $SECRET ($ENVNAME): " VALUE; echo
printf '%s' "$VALUE" | gcloud secrets create "iscan-$ENVNAME-$SECRET" --data-file=- ; unset VALUE
```

The private content files (the profile definition, prompt set, country table, price table, provider
configuration, PDF disclaimer) are stored the same way from a file on your own computer, never from the
repository: in Cloud Shell, **three-dot menu, Upload**, then
`gcloud secrets create iscan-dev-profile-definition --data-file=profile.json` and delete the uploaded file with
`rm profile.json`. Secret names: `provider-config`, `price-table`, `profile-definition`, `prompt-set`,
`country-table`, `pdf-disclaimer` (with the `iscan-dev-` or `iscan-prod-` prefix). They are mounted into the
application when the deployment runs; none is ever in an image.

To change a value later: `printf '%s' "$VALUE" | gcloud secrets versions add NAME --data-file=-`, then redeploy
(step 15 shows how).

---

## Part C. GitHub

### 11. Create the two environments

On GitHub, the repository, **Settings**, **Environments**:

1. **New environment**, name `dev`. Under **Deployment branches and tags**, choose **Selected branches** and
   add `main`.
2. **New environment**, name `production`. Same branch rule. Tick **Required reviewers** and add yourself.
   Leave "Prevent self-review" **off** (you are the only person).

*What it does:* production cannot start until you approve it in GitHub.

### 12. Give GitHub the (non-secret) addresses

**Settings, Secrets and variables, Actions, Variables tab, New repository variable.** Add these four. They are
addresses, not passwords; the deployment skips itself until all four exist:

| Name | Value |
|---|---|
| `GCP_PROJECT_ID` | your Project ID |
| `GCP_REGION` | `europe-west3` |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | the line starting `projects/` printed in step 7 |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | `iscan-deployer@YOUR-PROJECT-ID.iam.gserviceaccount.com` |

Then, in **each environment** (`dev` and `production`), under **Environment variables**, add:

| Name | Value |
|---|---|
| `CRAWLER_CONTACT_URL` | the public contact page that tells suppliers who is crawling their site (required: the worker refuses to start without it) |
| `EUR_PER_USD` | the conversion rate you use, for example `0.92` (needed when a USD-priced provider is selected) |

Do not add any password or key here.

### 13. First deployment

1. Merge any pull request to `main` (or, in **Actions**, open "Deploy dev" and **Run workflow** on `main`).
2. In **Actions**, "CI" runs, then "Deploy dev" starts by itself.

*What to expect:* 20 to 40 minutes the first time (it downloads and builds a 1.8 GB image). Steps in order:
build, check the images for secrets, push, migrate the dev database, deploy, health check. The run page shows
a summary of image sizes. Green means dev is live. If it is red, open the failed step and send the **log text**
(it contains no secret) to whoever maintains the project. Typical first-time causes: a missing secret
(the error names it), a missing API (step 4), a missing variable (step 12).

When it works, open the Cloud Run page in the console, service `iscan-web-dev`, and click its address.

### 14. Nothing to do for the address (no domain name needed)

Buyers use **one address only**: the `...run.app` address of the website service (`iscan-web-dev` or
`iscan-web-prod`). The website passes everything under `/api/` on to the API by itself, so the login stays valid
and you do not need to buy or set up a domain name. The deployment sets this up (it gives the website the address
of the API). The API also keeps its own `...run.app` address, but nobody needs it.

One more thing the deployment does by itself, so that nothing is left for you to do: Google's own request logs
write down the full address of every request, and an invitation link contains its secret. At every deployment a
filter is set (in Cloud Logging, "Log Router", the `_Default` sink, exclusion `iscan-no-invitation-urls`) so that
requests to invitation addresses are not stored. This is why the deployer robot gets the role
"Logs Configuration Writer" in step 6.

If you want a nicer address later (your own domain in front of the website service), that is a separate decision;
nothing in the application depends on it.

---

## Part D. Every day

### 15. Deploying and promoting

- **Dev updates by itself** after each merge to `main`, only if the tests passed.
- **To put what is in dev into production:** GitHub, **Actions**, "Promote to production", **Run workflow**
  (branch `main`). The run stops and asks you to approve: open it, **Review deployments**, tick `production`,
  **Approve and deploy**. It does not rebuild anything: it takes exactly the images that run in dev (by their
  digest), migrates the production database, deploys with no traffic, checks the health, and only then sends
  users to the new version. If the health check fails, users stay on the old version.
- **To change a secret:** add a new version (step 10) and run the deployment again.

### 16. Rolling back

The previous version is kept. In Cloud Shell:

```sh
gcloud run revisions list --service=iscan-api-prod --region="$REGION" --limit=5
gcloud run services update-traffic iscan-api-prod --region="$REGION" --to-revisions=REVISION-NAME=100
```

Do the same for `iscan-web-prod`. *Database changes are not undone* by a rollback: migrations only move forward,
and the previous version must still work with the new tables; if it cannot, ask the maintainers for a fix instead
of rolling back. To stop everything at once: `gcloud run services update iscan-api-prod --region="$REGION" --max-instances=0`
(and the same for the web service); undo by setting it back to `3`.

### 17. Costs, the worker, and alerts

- The **worker** (it carries out the profile runs and the drafting of assessments) is **off by default, in dev and
  in production**: the deployment creates it with zero instances and never switches it on. While it is off, nothing
  costs and nothing is computed: a run you start shows "En attente de démarrage" (waiting to start) and stays in
  the queue until the worker is on. Switch it on before a test run or a demo, and off afterwards. In Cloud Shell
  (replace `dev` by `prod` for production; `REGION` is `europe-west3`, type `REGION=europe-west3` first if Cloud
  Shell was closed since step 1):

  ```sh
  # ON: one worker
  gcloud beta run worker-pools update iscan-worker-dev --region="$REGION" --instances=1
  # OFF: no worker, no cost
  gcloud beta run worker-pools update iscan-worker-dev --region="$REGION" --instances=0
  ```

  A waiting run starts by itself a few seconds after the worker is on. Switching it off while a run is in progress
  interrupts that run; it is picked up again, or can be resumed, when the worker comes back. **Do not forget to
  switch it off**: an instance left on is the one thing here that costs by the hour. To see the state:
  `gcloud beta run worker-pools describe iscan-worker-dev --region="$REGION"`. The first deployment creates the
  worker, so these commands work only after step 13.
- The worker polls the database, so the production Neon database does not fall asleep while the worker runs. Check
  Neon's monthly compute allowance on your plan.
- The budget alert (step 2) is your safety net. If a warning arrives: open Billing, **Reports**, group by
  service, find the cause, and if needed use the stop command of step 16.
- **Email alerts for the application** (failed runs) and the on-call agent: step 18.
- Traces: console, **Trace**. Metrics: **Monitoring**, **Metrics explorer**, PromQL, for example the failure rate in
  `README.md` ("Observability"). Logs: **Logging**, **Logs Explorer**.

### 18. Alert and on-call agent (dev only, #53)

After the pull request of #53 is merged and deployed to dev, follow the set-up of
[`oncall-runbook.md`](oncall-runbook.md) in order. Each step has its exact commands:

1. Repository settings: allow GitHub Actions to create pull requests; create the label `incident`.
2. The model key: GitHub secret `ONCALL_ANTHROPIC_API_KEY` in the environment `oncall` (spending limit first).
3. The read-only account `iscan-oncall-reader` (logging viewer, trace user, monitoring viewer), usable only by
   `oncall.yml` on `main`; repository variable `ONCALL_READER_SERVICE_ACCOUNT`.
4. The relay `iscan-alert-relay` with its two secrets `iscan-dev-alert-webhook-token` and
   `iscan-dev-github-dispatch-token` (fine-grained token, *Actions: write* on this repository only, with an expiry).
5. The two notification channels: your email, and the relay webhook.
6. The alert policy: `make alert-apply ENV=dev`.

Then run the drill and the replay of the runbook once.

### Checklist of what you created (no values)

Project with billing and a EUR 10 budget; 11 APIs; Artifact Registry `iscan`; three service accounts;
Workload Identity pool `github` and provider `github-actions`; Neon projects `iscan-dev`, `iscan-prod`; secrets
`iscan-dev-*` and `iscan-prod-*`; GitHub environments `dev` and `production`; four repository variables.
