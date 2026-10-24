# Engineering process

- Tasks are GitHub issues on the `supplier-iscan` repository, one at a time.
- Read the acceptance criteria before starting and before closing.
- Commit regularly, on a branch per issue. Nothing is pushed or merged without the owner's go-ahead.

## Roles

Contracts are provider-neutral; each agent tool gets a thin wrapper that only sets its tools and points to them (see `AGENTS.md`).

- **PM** grooms a task before anyone implements it: `_docs/team/pm.md`
- **SWE** implements one groomed task: `_docs/team/swe.md`
- **QA** checks the result against the acceptance criteria: `_docs/team/qa.md`

## Orchestrator

The main session is the orchestrator. It launches the PM, the SWE and QA as subagents. It does not groom, implement or test itself.

## Lifecycle

1. Pick the next open issue from the backlog.
2. PM grooms it until it meets the definition of ready (`_docs/team/pm.md`).
3. SWE implements it.
4. QA verifies it and posts a verdict:
   - **PASS** → step 5
   - **FAIL (defect)** → back to step 3, with the QA comment as input
   - **FAIL (criteria)** → back to step 2: the PM re-grooms
5. The owner reviews the diff; the orchestrator closes the issue.
6. Repeat until the backlog is empty.

## Orchestration level

Full PM → SWE → QA by default. SWE + QA only when the PM shows in the issue that every condition below holds, and the owner approves:

- already groomed, acceptance criteria unambiguous
- no change to `openapi.yaml`, schema, authentication, security or data handling
- confined to one module
- no new dependency

QA is never dropped.

## Rules

- Do not skip step 2.
- The SWE does not close the issue.
- QA does not fix the code; it only posts a verdict.
- The orchestrator closes the issue only after a PASS and the owner's review.
- Regulatory content (GDPR, AI Act, contracts) comes only from sources reviewed by the owner. Any addition is marked as such with its source; no agent rewords a reviewed regulatory statement.
