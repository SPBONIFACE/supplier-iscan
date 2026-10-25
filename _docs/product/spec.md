# Supplier iScan: Functional Specification

Product behaviour of Supplier iScan: what it does, for whom, and how each feature is checked. Every acceptance
criterion below is meant to be verifiable by looking at the running application.

## Roles

- **Member:** a person in an organisation workspace who builds, reviews and compares supplier profiles.
- **Administrator:** runs an instance. Creates organisations, sets limits and provider configuration, sees usage and
  cost, never the content of an organisation's profiles.
- **Visitor:** opens the public demo without an account.

## User flows

### Flow 1: A member builds and reviews a supplier profile
1. The member opens an invitation link, sets a password, and lands in their organisation's workspace.
2. They choose the language (English or French) and start a new profile by typing a supplier name, optionally with hints (website, country, sector).
3. The identity agent searches public registries and presents the most likely company. The member confirms it, or corrects it in chat ("no, the French subsidiary"; "their site is …"). After confirmation, a structured identity record is stored (F1).
4. A profile run starts in the background. The screen shows progress by stage (identity → collection → extraction → assessment) and the organisation's remaining quota.
5. The worker collects evidence (F2), extracts the profile fields with verified quotes (F3), and drafts the assessment (F8).
6. The member reviews the supplier card in a side panel: approves or corrects each fact (F4) and each assessment statement (F8).
7. The member ticks two or more profiles from their organisation's previous runs and opens the side-by-side comparison (F5).
8. The member downloads the card or the comparison as PDF (F9).

### Flow 2: An administrator onboards an organisation
1. The administrator creates an organisation and a first single-use invitation for the person who will accept the instance's terms on the organisation's behalf.
2. That person identifies the organisation's legal entity, chooses the document language, downloads the terms documents, ticks an unticked box confirming their authority, and confirms. Only then is the organisation activated.
3. Further members are invited up to the configured seat limit; each accepts the individual account-use rules.
4. The administrator sees, per organisation: members, profiles used against the quota, access end date, LLM cost and errors. Never supplier names or profile content.

### Flow 3: A visitor explores the demo
1. A visitor opens the public URL and chooses "Explore the demo" (no account).
2. They browse a fixed set of pre-built demo profiles, the comparison and the PDF export, with the AI assessment drafts and a visible disclaimer.
3. Actions that would trigger an LLM call (new profile, re-run) are disabled with an explanation.

### Flow 4: Self-hosting
1. A developer clones the repository, copies the example environment file, sets their own provider API keys and starts everything with one command.
2. A single local administrator account is created on first start; limits are configurable and off by default.

## Features

### F1: Confirm supplier identity
**Description:** a conversational agent turns a supplier name and optional hints into a confirmed identity record. Candidates come from public registries (Wikidata, GLEIF) and web retrieval. Hints change the ranking only and never exclude a candidate. The member can always fall back to entering the website directly.

**Acceptance criteria**
- [ ] Given a name with several homonyms, the agent presents the top candidate with name, website, country, sector and a one-line description, and offers the other candidates on request.
- [ ] A hint that contradicts the true company (e.g. wrong country) lowers its rank but never removes it from the candidate list.
- [ ] The member can correct the agent in free text; the agent searches again and presents a new candidate.
- [ ] "None of these, enter the website" creates an identity from the given domain, after checking that the domain responds.
- [ ] The exchange ends only when the member explicitly confirms; the stored identity record conforms to the `IdentityRecord` schema.
- [ ] After collection, if the confirmed company name does not appear in the collected content of its website, the profile is flagged "identity to verify".
- [ ] If both registries are unreachable, the agent says so and offers the website fallback; no error page.
- [ ] At the first interaction, before any input, the chat states that the member is talking to an AI assistant, in the UI language, with exactly this text:
  - English: "You are talking to an AI assistant. Its role: supplier research. As AI can make mistakes, please verify the legal entity of the selected supplier and the sources provided."
  - French: "Vous échangez avec un assistant IA. Son rôle : effectuer des recherches fournisseur. L'IA pouvant faire des erreurs, veuillez vérifier l'entité légale du fournisseur sélectionné ainsi que les sources proposées."
- [ ] When the confirmed legal form is a sole trader or another natural-person business, the identity record is flagged `natural_person` (see F8, excluded uses).

### F2: Adaptive evidence collection
**Description:** a background job collects public evidence about the confirmed supplier: website pages (sitemap and link discovery), linked PDF reports, and web retrieval through the retrieval provider. When a source fails, the job changes strategy within a capped number of attempts.

**Acceptance criteria**
- [ ] For a reachable website, the job collects at least the home, about, sustainability/ESG, certifications/quality and locations pages when they exist, plus linked PDF reports up to a size limit.
- [ ] Every fetched source is stored with its URL, fetch timestamp, content type and extracted text.
- [ ] robots.txt is respected; requests are rate-limited per domain.
- [ ] Before crawling a domain, the job checks and records its crawl-permission signals (robots.txt, the TDM Reservation Protocol `tdm-reservation` header and `/.well-known/tdmrep.json`, the suppression list) in a `CrawlPermission` record. A domain with a reservation is not crawled, and the member sees "source excluded at the site owner's request". A robots.txt block aimed at AI crawlers by name (e.g. GPTBot, ClaudeBot, Google-Extended, CCBot, PerplexityBot) also counts as a reservation.
- [ ] The crawler identifies itself with a User-Agent that names the service and links to a contact page; it never bypasses authentication, CAPTCHA or other access controls.
- [ ] Before any text is sent to an external LLM provider, personal data is redacted: email addresses and phone numbers removed, every person's name replaced by `[…]`. Facts keep the role without the name. Only the redacted text is stored.
- [ ] Each failure (HTTP error, timeout, empty content, blocked by robots.txt) is logged with the strategy tried and the next strategy chosen; the attempt cap is enforced.
- [ ] Targets resolving to private, loopback or link-local addresses are refused.
- [ ] If every strategy fails, the run ends in "insufficient sources" with the failure log visible to the member; it does not count against the quota.

### F3: Grounded extraction
**Description:** the structuring provider fills the profile fields (see *Profile definition*) from the collected sources. Every value carries a verbatim quote, its source URL and fetch date; a value without a verifiable quote is rejected.

**Acceptance criteria**
- [ ] Every extracted value conforms to the `FieldExtraction` schema: value, quote, source id, or the explicit status `not_found`.
- [ ] A value is kept only if its quote is found in the stored text of the cited source (after whitespace and typography normalisation); otherwise it is discarded and counted as a grounding failure.
- [ ] Quotes are stored and shown in their source language; field labels follow the UI language.
- [ ] "Not found" is displayed as "No public evidence found", never as a negative statement about the supplier.
- [ ] Each fact shows "Found in <source> on <date>".
- [ ] Each fact carries a source type, `supplier_claim` or `third_party`, derived from the source's domain relative to the confirmed supplier website and its registry identifiers; the card labels it "Supplier's own claim" or "Third-party source".
- [ ] Quotes are limited to the passage needed to support the fact (at most 300 characters), attributed (author when identified, publisher, URL, date) and visually distinct from the app's own text. A passage containing redactions is labelled "Redacted extract", each omission marked `[…]`, and matched against the stored redacted text.
- [ ] Text produced by the retrieval provider is never shown as a fact; only passages matched in a fetched source become facts.
- [ ] Certification facts show a "Verify on IAF CertSearch" link; the app never states that a supplier is not certified.

### F4: Review
**Description:** organisation members approve or correct each extracted fact.

**Acceptance criteria**
- [ ] Each fact has the status `proposed`, `approved` or `corrected`; any organisation member can change it; the change records who and when.
- [ ] A correction keeps the original AI value and quote alongside the corrected value.
- [ ] The card shows how many facts are still `proposed`.

### F5: Supplier card and side-by-side comparison
**Description:** the supplier card opens in a side panel. The member ticks profiles from their organisation's previous runs and compares them field by field.

**Acceptance criteria**
- [ ] The card shows: a header (name, website, country, sector, last refresh), one row per field with value, status and a source chip that reveals the quote and link, and the assessment section.
- [ ] The comparison accepts 2 or more profiles chosen from the organisation's own runs; up to 4 are shown as side-by-side columns, beyond that as a compact matrix.
- [ ] Every compared value keeps its source chip.
- [ ] A profile from another organisation can never be selected or opened (see *Security model*).

### F6: LLM provider choice
**Description:** the provider is chosen per role, retrieval and structuring, among Claude, Gemini, OpenAI, Mistral and Perplexity. Defaults: Perplexity for retrieval, Gemini Flash for structuring, both subject to the evaluation results.

**Acceptance criteria**
- [ ] The administrator sets the provider per role; a self-hoster sets providers and keys in configuration. Keys are never written to the database, logs or telemetry.
- [ ] Each run records the provider and model ID used per role, its token usage and its cost.
- [ ] A provider error is reported with the provider name and without the key; the run can be retried.
- [ ] Runs use only **approved provider configurations**: one record per exact API, model ID, endpoint, training setting, retention, region and transfer mechanism. A run never falls back to a configuration outside this list; a configuration with an unverified point stays disabled.
- [ ] SDK versions are pinned. The same extraction contract tests (schema, citations, quote matching) run for every approved provider, model and output mode.

### F7: Access, limits and data control
**Description:** invitation-only organisations with configurable limits, terms acceptance, member-controlled deletion, and a read-only demo mode.

**Acceptance criteria**
- [ ] An invitation link is single-use and expires after a configured delay; an organisation has at most the configured number of seats.
- [ ] An organisation's access lasts a configured period from its activation; the administrator can extend it. A profile run is refused once the organisation's profile quota is used or its access has ended, with the reason stated. Runs that end in "insufficient sources" do not count.
- [ ] A profile run is refused once the instance's recorded LLM spend for the month reaches the configured cap; existing profiles remain readable.
- [ ] Each run has a hard cost budget with a bounded number of retries, measured from billed usage (failed and retried calls, search tools and reasoning tokens included). When the budget is exhausted, the run stops and the profile is marked "partial" with the sections not yet covered.
- [ ] Every run, login and failed login is recorded in the usage log with user, organisation and timestamp.
- [ ] An organisation is activated only after a representative has identified its legal entity, received the complete terms documents in the selected language before activation, ticked an unticked box stating their authority, and confirmed. The app records acceptor, organisation, authority statement, timestamp, language and exact document versions, keeps immutable copies, and generates the accepted package for the administrator to send. Further members accept individual account-use rules. A material change to the documents requires renewed acceptance; earlier versions are preserved.
- [ ] A member can stop a running run, delete any profile of the organisation at any time, and request deletion of all the organisation's data. At the end of access, the organisation chooses deletion or return; return is one archive (each profile as PDF plus a JSON file following a published schema), after which the data is deleted. Deletion covers source text, facts, assessments, buyer inputs and derived data, and is confirmed to the requester.
- [ ] Demo mode needs no account, shows only the pre-built demo profiles, and cannot start an LLM call.

### F8: Evidence-backed assessment draft
**Description:** the structuring provider drafts SWOT points, risk indicators and fit statements. Every statement cites at least one fact of the profile, or is an explicit evidence gap stating what evidence would close it.

**Acceptance criteria**
- [ ] Every statement conforms to the `AssessmentStatement` schema; statements citing no existing fact are rejected automatically.
- [ ] A statement may carry a level (low / medium / high) only together with its cited facts; there is no aggregate numerical score.
- [ ] An evidence gap names the missing evidence. For financial stability, the message comes from the financial guidance (see *Financial evidence guidance*), never from the LLM.
- [ ] Every statement is labelled "AI draft, pending your validation" until a member approves, corrects or deletes it.
- [ ] Fit statements are drafted only against criteria the member entered for this profile; with none entered, the fit section reads "Enter your criteria to assess fit".
- [ ] Fields of kind `buyer` are never drafted by the AI; they are free-text fields for the member.
- [ ] Every statement stores its provenance: provider, model ID and version, generation time, and review status (`ai_draft`, `approved`, `corrected`, `deleted`, with reviewer and time), shown on demand.
- [ ] **Excluded uses:** no assessment of natural persons. No statement evaluates an individual employee or manager; no credit, financial-stability or risk statement is drafted for an identity flagged `natural_person`, whose section reads "Not assessed: natural-person business".

### F9: PDF download
**Description:** server-side PDF of a supplier card and of a comparison, in the UI language, using the design system.

**Acceptance criteria**
- [ ] The PDF contains every fact with its status, quote excerpt, source URL and date, and the assessment with its labels.
- [ ] The PDF shows the disclaimer, the generation date and the source-content deletion date.
- [ ] AI-generated sections are visibly labelled ("AI draft" or "reviewed by …") with their provenance (model, version, generation time, review status), and the file carries this provenance in its metadata.
- [ ] PDF generation for a 4-profile comparison completes in under 15 seconds.

## Profile definition

The sections and fields of a supplier profile are **loaded at runtime from a profile-definition file**, not hard-coded.
Each field declares its kind:

- **`fact`:** extracted with a verified quote (F3)
- **`assessment`:** drafted from cited facts (F8)
- **`buyer`:** entered by the member only, never generated

The repository ships an **example definition** with four sections (company overview, production footprint,
certifications, SWOT). An instance can supply its own definition through configuration; the application validates it
at startup against a published schema.

## Financial evidence guidance

When financial evidence is missing, the message is built from rules in code and a **country table loaded at runtime**
(the repository ships a minimal example table). The LLM never writes it.

1. **Entity and period.** Guidance is computed for the confirmed legal entity and a financial year; the supplier's own accounts are distinguished from parent-company or consolidated accounts.
2. **Existence is separate from accessibility.** Each document gets one access status: `public_download`, `free_registration`, `paid`, `reduced_disclosure`, `confidentiality_declared`, `no_filing_identified`, `registry_unavailable`. A paid, reduced or temporarily unreachable document is never reported as "unavailable"; a failed registry request is never read as evidence that no filing exists.
3. **Name the missing evidence:** income statement, full notes, audit report, a more recent period, or supplier-entity rather than group accounts.
4. **Specific fallback:** when public filings are unavailable, outdated or insufficient, the message names the documents to request from the supplier. Supplier-provided documents are recorded by type (statutory accounts, audited statements, tax schedules, management accounts).
5. **Commercial sources are a separate evidence class.** No credit score, estimate or commercial report replaces filed financial statements.

Each country row carries a "last checked" date. Where access is paid, the app links to the registry and never buys documents.

## Architecture constraints
- **API client layer:** every backend call from the frontend goes through one isolated client module (`frontend/src/lib/api.ts`), typed against the OpenAPI contract. No vendor SDK and no direct database call from a component.
- **Contract first:** `openapi.yaml` is the source of truth; it changes before the code.
- **Long-running work:** profile runs execute in a worker through a PostgreSQL job queue, never in the request path.
- **LLM output:** structured output validated against typed schemas; no parsing of free-text LLM output.
- **Runtime content:** the profile definition, the financial country table and the prompts of the LLM features are data files loaded at startup, validated against published schemas; example versions ship with the repository, and an instance can supply its own through configuration. An invalid or missing file stops startup with an error naming it.
- **Supply chain:** `pnpm` with exact pinned versions and a committed lockfile, never `npm install` or `npx`; `uv` with a committed `uv.lock`. Any pre-1.0 or little-used dependency is audited before use (install scripts, dependency count, domains contacted, `exec`/`eval`). Secrets are referenced by name only and never committed.
- **Identifier language:** English for all identifiers (tables, columns, fields, routes, variables), whatever the UI language.

## Data model & ownership
| Entity | Key fields | Created by | Contains personal data |
| :--- | :--- | :--- | :--- |
| Organisation | id, name, seat limit, profile quota, access_ends_at, created_at | Administrator | no |
| User | id, organisation_id, email, password_hash, role (`admin`, `member`), created_at, last_login_at | Administrator (invitation) / user (password) | yes |
| Invitation | id, organisation_id, token_hash, expires_at, used_at | Administrator | yes (email) |
| DocumentVersion | id, kind (`terms`, `data_processing`, `account_rules`, `privacy_notice`, `legal_notices`), language, version, content_hash, published_at, file (immutable) | Administrator | no |
| Acceptance | id, organisation_id, user_id, kind (`organisation`, `account_rules`), legal_entity, authority_statement, document_version_ids, language, accepted_at | Representative / member | yes |
| SupplierIdentity | id, organisation_id, legal_name, website, country, sector, registry ids, natural_person, confirmed_by, confirmed_at | Member (F1) | no |
| ProfileRun | id, organisation_id, identity_id, status, stage, providers and model IDs per role, profile-definition hash, prompt-set hash, tokens, cost, started_at, finished_at | Member | no |
| Source | id, run_id, url, fetched_at, content_type, redacted_text, author, delete_after | Worker | residual only (redaction can miss a name; treated as personal data) |
| CrawlPermission | domain, robots_result, tdm_reservation, suppression_hit, decision, checked_at | Worker | no |
| SuppressionEntry | id, kind (`domain`, `person_name`), value, reason, requested_at, added_by, removed_at, removed_by, removal_reason | Administrator (on objection or rights request) | yes (`person_name`) |
| Fact | id, run_id, section, field, value, quote, quote_redacted, source_id, source_type, status, original_value, reviewed_by, reviewed_at | Worker / member | possible (identifiable quotes are treated as personal data) |
| AssessmentStatement | id, run_id, kind, text, level, cited_fact_ids, gap_evidence, provider, model_id, generated_at, status, reviewed_by, reviewed_at | Worker / member | no |
| BuyerInput | id, run_id, field, text, updated_by, updated_at | Member | no |
| ProviderConfig | id, provider, api, model_id, endpoint, training_setting, retention, region, transfer_mechanism, verified_at, enabled | Administrator | no |
| UsageEvent | id, organisation_id, user_id, kind, cost, created_at | System | yes |
| DemoProfile | read-only copy of selected runs, flagged `demo` | Administrator | no (names stripped) |

## Security model
- **Authentication:** invitation link, then email and password (argon2 hash), session cookie (HttpOnly, Secure, SameSite=Lax). Self-hosted: one local administrator created on first start. Demo mode: no authentication, read-only.
- **Access rules:**

  | Entity | Read | Write |
  | :--- | :--- | :--- |
  | Organisation | its members; administrator | administrator |
  | User, Invitation | the user themself; administrator | administrator (create, revoke); user (own password) |
  | SupplierIdentity, ProfileRun, Fact, AssessmentStatement, Source, BuyerInput | members of the owning organisation only | members (review, buyer inputs); worker (create facts and statements) |
  | Run metadata (status, cost, errors) | owning organisation; administrator | system |
  | Supplier names, fact values, quotes, corrections, criteria, notes, assessments | owning organisation only, **not the administrator** | owning organisation; worker |
  | UsageEvent | administrator | system |
  | DocumentVersion | everyone (published documents) | administrator |
  | Acceptance | owning organisation; administrator | the accepting user (create only, never edited) |
  | ProviderConfig, SuppressionEntry, CrawlPermission | administrator | administrator (configs, suppression); worker (crawl permissions) |
  | DemoProfile | everyone | administrator |

  A request for another organisation's resource returns 404 (no existence leak).
- **Allowed origins (CORS):** local `http://localhost:5173`; deployed environments: exactly the frontend origin of each environment, set by configuration. No wildcard.
- **Secrets:** provider API keys, database URL, session secret: a secret manager in deployed environments, CI secrets for the pipeline, a gitignored `.env` (with a committed `.env.example`) for self-hosting. Never in the repository, logs or telemetry.

## Data protection and source safeguards
- **Redaction before any LLM call** and storage of redacted text only (F2).
- **Crawl permissions** checked and recorded per domain; TDM reservations and AI-crawler blocks honoured (F2).
- **Quotes:** short, attributed, visually distinct from the app's own analysis; a rights-complaint and takedown route is published.
- **Suppression list:** a person or domain can ask to be excluded; matching extracts are redacted in existing profiles and in future runs. The administrator can remove an entry (for example one added by mistake), stating a reason; each addition and removal is recorded with who and when, and a removal applies to future runs only.
- **No cross-organisation reuse:** source text, profiles, indexes and caches containing personal data are never shared between organisations.
- **Retention per data class,** configurable: redacted source text, profiles, accounts and usage events, security logs, telemetry. Each profile shows when its source content will be deleted.
- **AI transparency:** AI disclosure at the first chat interaction (F1); provenance and review status on every AI statement and in the PDF (F8, F9).
- **Excluded uses:** no natural-person credit scoring, no employee or candidate evaluation, no automated decision about individuals.

## Integrations
| System | Direction | Payload | Failure behaviour |
| :--- | :--- | :--- | :--- |
| Wikidata API | out | candidate: label, website, country, industry, Wikidata id | skip source, continue with others, tell the member; descriptive User-Agent; honour `429` / `Retry-After`; at most 5 parallel queries; identifiers cached |
| GLEIF API | out | candidate: legal name, LEI, registered address, legal form | skip source, continue with others, tell the member; throttled below 60 requests per minute; identifiers cached |
| Supplier websites and PDFs | out (HTTP GET) | HTML / PDF → extracted text, URL, fetched_at | retry with backoff, then next strategy; logged (F2) |
| Retrieval provider | out | query → cited URLs; cited URLs are fetched and verified like any source; the provider's answer text is never shown as a fact | next strategy; the run continues with other sources |
| Structuring provider | out | structured `IdentityProposal`, `FieldExtraction[]`, `AssessmentStatement[]`, validated against schemas | retry once; on schema failure the item is dropped and counted; on outage the run pauses and can be resumed |

## LLM features
| Feature | Input | Structured output | What "good" looks like |
| :--- | :--- | :--- | :--- |
| Identity agent (F1) | name, hints, registry candidates, chat turns | `IdentityProposal` {candidate, confidence, question_to_user} → `IdentityRecord` on confirmation | right company in ≤ 3 exchanges; never discards a candidate because of a hint |
| Field extraction (F3) | field definitions, source texts | `FieldExtraction[]` {field, value, quote, source_id} or `not_found` | 100% of kept quotes found in source; ≥ 90% accuracy and ≥ 70% exhaustiveness on the reference set |
| Assessment drafting (F8) | facts, buyer criteria | `AssessmentStatement[]` {kind, text, level?, cited_fact_ids, gap_evidence?} | 100% of statements cite valid facts or name the missing evidence; ≥ 80% judged useful by a domain reviewer |
| Retrieval (F2) | identity record, field groups lacking evidence | list of URLs with snippets | finds sources the website crawl missed; every URL verifiable |

The instructions sent to the model for each feature are **loaded at runtime from a prompt file**, not hard-coded, so that an instance can adapt them like the profile definition. Prompts carry instructions only: schema validation, the grounding check, citation checks, redaction and the excluded uses are enforced in code whatever a prompt says. Collected text, chat turns, facts and buyer criteria are inserted as delimited data, never into the instructions. Each run records the version of the prompts it used, and the evaluation reports results for a given prompt version.

## Non-functional requirements
- **Performance:** a profile run completes in under 10 minutes; API responses outside runs under 500 ms at p95; a scale-to-zero cold start is acceptable.
- **Availability:** best effort; the public demo mode stays reachable.
- **Accessibility:** WCAG 2.1 AA, 0 critical issues; keyboard-operable review and comparison.
- **Localisation:** English and French UI, chosen by the user and remembered; quotes stay in their source language; dates and numbers formatted per locale.
- **Design:** each screen is built from an approved mock-up; shared design tokens and components; the PDF uses the same design system.
- **Operability:** one command starts the whole system locally (Docker Compose, database included); one command runs unit and integration tests; CI runs tests on every pull request, deploys to dev automatically and promotes to prod manually; the profile run is instrumented with metrics, traces and structured logs sharing a trace ID, with no personal data or credentials in telemetry; an alert fires on user impact (profile-run failure rate); an on-call agent is woken by the alert and proposes or applies a fix.

## Robustness cases
| Case | Expected behaviour |
| :--- | :--- |
| A dependency is down (registry, website, LLM provider, database) | The member sees which dependency failed in plain language; the run pauses or ends without counting against the quota; nothing crashes; the failure is logged and traced |
| Malformed input (empty name, invalid URL, oversized PDF, invalid schema from the LLM) | Validation error with a clear message; oversized documents skipped and logged; invalid LLM items dropped and counted |
| Special characters / non-English text (accents, CJK names, French and German sites) | Names, quotes and search work in any script; quotes matched after Unicode normalisation; the UI renders them correctly |
| Unauthorised request (no session, another organisation's resource, demo visitor starting a run) | 401 without session; 404 for another organisation's resource; 403 for a demo visitor attempting a write |
| Prompt injection inside a crawled page | Collected text is passed as data, never as instructions; values still require a verbatim quote, so injected claims cannot appear without a source |
| URL pointing to a private network address | Refused before any request is made |
| Quota, access period or monthly cap reached mid-run | The running job finishes; new runs are refused with the reason |
| Seat limit exceeded | Refused; unusual login patterns visible to the administrator in the usage log |
| Site expresses a TDM reservation or is on the suppression list | Domain not crawled; recorded in `CrawlPermission`; the member sees "source excluded at the site owner's request" |
| Rights request or objection from a person named in a source | Name added to the suppression list; matching extracts redacted in existing profiles; future runs redact it |
| Run budget exhausted | Run stops; profile marked "partial" with the uncovered sections listed |
| Provider configuration not approved, or a failover target outside the list | Call refused; run pauses with an administrator-facing error; no silent fallback |

## Out of scope
- Free-form Q&A chat about a supplier; Excel export.
- Sharing profiles between organisations.
- Aggregate numerical scores about named companies.
