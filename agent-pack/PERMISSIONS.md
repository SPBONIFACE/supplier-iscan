# Permissions of the coding agents

What the agents that build Supplier iScan may do without asking, what they must never do, and which layer enforces
each rule. Source of the rules: [`AGENTS.md`](../AGENTS.md) (Rules).

| Rule | Layer |
| :--- | :--- |
| Never read, edit or write a `.env` file at any depth (`.env`, `backend/.env`, `.env.local`), also through `cat`, `source`, redirections. `.env.example` is allowed. | Hook `hooks/guard.py` (any name, any depth) + `permissions.deny` in `.claude/settings.json` (the common names) |
| Never `npm install`, `npm i`, `npm ci`, `npx`, also in a pipeline or after `&&`. Use `pnpm` and `uv`. | Hook + `permissions.deny` |
| Never add or upgrade a dependency from the command line: `uv add`, `uv pip install`, `pip install`, `pnpm add`, `pnpm install <package>`, `pnpm i <package>`, `pnpm up`/`update`/`upgrade`, also in a pipeline, after `&&` or through `sudo`, `env`, `uv run`, `bash -c`, `pnpm exec`. `pnpm install` without a package and `uv sync` stay allowed (`make install`). | Hook (block) |
| Every direct dependency of `backend/pyproject.toml`, `agent-pack/pyproject.toml` and `frontend/package.json` is in `_docs/process/approved-dependencies.md` with the same exact version; an entry marked removed is not approved | `make lint` and CI (`agent-pack/scripts/check_dependencies.py`) |
| The approved-dependencies list changes only with the owner's approval: an Edit or Write of it, or a shell command that writes it (redirection, `tee`, `cp`, `mv`, `sed -i`, an interpreter, `git checkout`), asks the owner | Hook (ask: the owner sees a prompt with the reason); the pull request waits for the owner |
| Hook input that cannot be parsed is blocked | Hook |
| No push or merge without the owner's go-ahead (task branches follow the delivery mode of `_docs/process/process.md`) | Owner's review; no setting in this repository grants push or merge |
| No change of scope, no change of `openapi.yaml` after the code | Owner's review (pull request review) |

## May do without asking

Reading the repository; `make install|test|lint|run|stop`; `uv run`, `uv sync`; `pnpm install`, `pnpm exec`,
`pnpm test`; `git status|diff|log|add|commit` on a branch; `gh issue view`, `gh pr view`. This is guidance for the
owner's personal settings: the committed `.claude/settings.json` holds **no allow rule and no mode**. Whatever is
allowed is decided in the uncommitted `.claude/settings.local.json`, which the pack never touches.

## Limits

- `permissions.deny` cannot carve out `.env.example`, so it lists the common names (`.env`, `.env.local`,
  `.env.development`, `.env.production`, `.env.staging`, `.env.test`); the hook covers every other name.
- Known limits of the hook, not caught on purpose: globs and shell expansion that build a name at run time
  (`cat .e*`, `cat .$(echo env)`). They are backstopped by `permissions.deny` (common names) and by the project
  rule in `AGENTS.md`, enforced by the owner's review. A literal `.env` anywhere in a command string (also inside
  `python -c "..."`), in any letter case, is blocked; `.env.example` is allowed.
- The ask on the approved-dependencies list is a PreToolUse `permissionDecision: "ask"` (Claude Code hooks
  reference). It prompts the owner in interactive, auto and sub-agent sessions; where nobody can answer
  (`claude -p`, `dontAsk`), Claude Code denies the call, so it fails safe. If the owner answers yes, that is the
  approval; an agent must never answer it for itself. A deny or ask rule in settings is still applied on top.
- What can still get past the dependency rules: a package manager the hook does not know (`yarn`, `poetry`,
  `conda`, `bun`), a name built at run time (`pnpm "ad""d" x`, `$CMD`), `uv run --with`, a script or `make`
  target that installs, a hand edit of `pyproject.toml`, `package.json` or a lockfile (caught afterwards by
  `make lint`, not by the hook), and a write to the list through a variable, glob or script file. The list check in
  `make lint` and CI is the net for edits to the manifests; the owner's review of the pull request, for the list.
  A SWE who edits the list and the manifest together passes `make lint`: only the hook's ask and the review stop it.
- Heredoc text (an issue or pull request body after `<<'EOF'`) is data, not shell, and is no longer tokenized; a
  heredoc fed to a shell or interpreter, or with an unquoted delimiter, is still checked. `.env` names are still
  searched in the whole text.
- The hook only exists in Claude Code. Other tools rely on the owner's review.
- Shell parsing is conservative: some harmless commands that mention `.env` or `npm install` in a string can be
  blocked. That is the intended side of the error.
