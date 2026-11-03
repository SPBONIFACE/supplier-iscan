# Engineering process

- Tasks are GitHub issues on the `supplier-iscan` repository. Independent tasks run in parallel waves (see *Delivery mode*).
- Read the acceptance criteria before starting and before closing.
- Commit regularly, on a branch per issue. Pushing a task branch, opening its pull request and merging it on PASS are part of the lifecycle; any other push or merge needs the owner's go-ahead.

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
6. The orchestrator merges the pull request, which closes the issue, when QA says PASS, CI is green and no owner gate applies (see *Delivery mode*). When an owner gate applies, the owner reviews the pull request first and the orchestrator merges on the owner's go-ahead.
7. Repeat until the backlog is empty.

## Orchestration level

Full PM → SWE → QA by default. SWE + QA when the issue was already groomed by the PM and nothing it depends on has changed since (owner's standing approval, 26 Oct 2026); otherwise only when the PM shows in the issue that every condition below holds, and the owner approves:

- already groomed, acceptance criteria unambiguous
- no change to `openapi.yaml`, schema, authentication, security or data handling
- confined to one module
- no new dependency

QA is never dropped for the risky tasks listed under *Delivery mode*.

## Rules

- Do not skip step 2.
- The SWE does not close the issue.
- QA does not fix the code; it only posts a verdict.
- The orchestrator merges, and so closes the issue, only after a PASS and a green CI, and after the owner's review when an owner gate applies.
- Acceptance criteria may refer to the task's own pull request and its CI check: the pull request exists before QA.
- Regulatory content (GDPR, AI Act, contracts) comes only from sources reviewed by the owner. Any addition is marked as such with its source; no agent rewords a reviewed regulatory statement.

## Delivery mode

- **Sequential, bundled work (usage budget, 2 Nov 2026).** One agent runs at a time. A SWE may take 2–3 closely related issues in one run, one branch and pull request per issue where practical. Agents run on a lighter model than the orchestrator.
- **QA proportionate to risk.** A separate QA agent verifies every task touching security, authentication, personal data, crawling or the LLM boundary (redaction, prompts, grounding). For other tasks, the SWE's tests, a green CI and the owner's digest are the check; the orchestrator reads the diff summary before merging.
- **Merge on PASS.** The orchestrator merges when QA says PASS, CI is green and the pull request stays within its issue.
- **Owner gates.** A pull request waits for the owner's review when it adds a dependency that is not in `_docs/process/approved-dependencies.md`, changes the spec or the scope, contains regulatory text, or builds a screen whose mock-up the owner has not approved. Design deliverables are always approved by the owner. A pull request that changes `_docs/process/approved-dependencies.md` always waits for the owner, even when green. The SWE never edits that file; the orchestrator does it only after the owner's approval. Three layers back this: `make lint` fails on any direct dependency missing from the list or at another version (`agent-pack/scripts/check_dependencies.py`), the hook blocks `uv add`, `pip install`, `pnpm add` and the like, and the hook asks the owner before any edit of the list.
- **Daily digest.** Once a day the orchestrator gives the owner a digest: what was merged (with links), QA verdicts, anything unusual. The owner may ask for any merged change to be reverted or amended.
- **Batched approvals.** Dependencies are approved once, as a list (`_docs/process/approved-dependencies.md`); open questions are answered in batches.
- **Long runs.** Work that must continue while the owner is away runs on infrastructure that stays on (cloud agents, or Claude Code on a server), never on the owner's laptop.
