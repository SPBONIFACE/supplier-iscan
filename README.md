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
- **Task tracker:** the GitHub issues of this repository.

## Running it

Instructions arrive with the first code: `make run` will start the whole system, database included, and
`make test` will run the test suites.
