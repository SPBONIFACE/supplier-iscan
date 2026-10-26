# Engineering process

- Tasks are GitHub issues on the `supplier-iscan` repository, one at a time.
- Read the acceptance criteria before starting and before closing.
- Commit regularly, on a branch per issue. Pushing a task branch and opening its pull request are part of the lifecycle (step 4); any other push, and every merge, needs the owner's go-ahead.

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
3. SWE implements it on the issue's branch and pushes the branch.
4. The orchestrator opens the pull request (`Closes #<issue>`), so CI runs on it.
5. QA verifies the pull request, including its CI result, and posts a verdict on the issue:
   - **PASS** → step 6
   - **FAIL (defect)** → back to step 3, with the QA comment as input; the pull request stays open
   - **FAIL (criteria)** → back to step 2: the PM re-grooms
6. The owner reviews the pull request; on the owner's go-ahead the orchestrator merges it, which closes the issue.
7. Repeat until the backlog is empty.

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
- The orchestrator merges, and so closes the issue, only after a PASS and the owner's review.
- Acceptance criteria may refer to the task's own pull request and its CI check: the pull request exists before QA.
- Regulatory content (GDPR, AI Act, contracts) comes only from sources reviewed by the owner. Any addition is marked as such with its source; no agent rewords a reviewed regulatory statement.
