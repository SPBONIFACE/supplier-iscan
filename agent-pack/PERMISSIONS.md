# Permissions of the coding agents

What the agents that build Supplier iScan may do without asking, what they must never do, and which layer enforces
each rule. Source of the rules: [`AGENTS.md`](../AGENTS.md) (Rules).

| Rule | Layer |
| :--- | :--- |
| Never read, edit or write a `.env` file at any depth (`.env`, `backend/.env`, `.env.local`), also through `cat`, `source`, redirections. `.env.example` is allowed. | Hook `hooks/guard.py` (any name, any depth) + `permissions.deny` in `.claude/settings.json` (the common names) |
| Never `npm install`, `npm i`, `npm ci`, `npx`, also in a pipeline or after `&&`. Use `pnpm` and `uv`. | Hook + `permissions.deny` |
| Hook input that cannot be parsed is blocked | Hook |
| No push or merge without the owner's go-ahead (task branches follow the delivery mode of `_docs/process/process.md`) | Owner's review; no setting in this repository grants push or merge |
| No new dependency, no change of scope, no change of `openapi.yaml` after the code | Owner's review (approved-dependencies list, pull request review) |

## May do without asking

Reading the repository; `make install|test|lint|run|stop`; `uv run`, `uv sync`; `pnpm install`, `pnpm exec`,
`pnpm test`; `git status|diff|log|add|commit` on a branch; `gh issue view`, `gh pr view`. This is guidance for the
owner's personal settings: the committed `.claude/settings.json` holds **no allow rule and no mode**. Whatever is
allowed is decided in the uncommitted `.claude/settings.local.json`, which the pack never touches.

## Limits

- `permissions.deny` cannot carve out `.env.example`, so it lists the common names (`.env`, `.env.local`,
  `.env.development`, `.env.production`, `.env.staging`, `.env.test`); the hook covers every other name.
- The hook only exists in Claude Code. Other tools rely on the owner's review.
- Shell parsing is conservative: some harmless commands that mention `.env` or `npm install` in a string can be
  blocked. That is the intended side of the error.
