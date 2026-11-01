# Agent extension pack

Development tooling for the coding agents that build Supplier iScan; not part of the product. Each part enforces
or eases a rule the project already has ([`AGENTS.md`](../AGENTS.md)).

| Part | What it does | Rule behind it |
| :--- | :--- | :--- |
| Skill `evidence-wording` (`skills/evidence-wording/SKILL.md`) | Rewrites user-facing text so absence is "No public evidence found", sources are labelled, extracts show `[…]`, AI text is labelled "AI draft, pending your validation". Links to `_docs/team/pm.md` and the spec; copies nothing. | Grounding and wording rules |
| MCP server `supplier-iscan-contract` (`mcp_server/server.py`) | Read-only, local, stdio: `list_operations`, `get_operation(method, path)`, `get_schema(name)` over `openapi.yaml`. No network, no key. Reads `openapi.yaml` of the current directory, or the file in `OPENAPI_FILE`. | `openapi.yaml` is the contract |
| Hook (`hooks/guard.py`, wired by `hooks/hooks.json`) | Blocks `.env` access at any depth and `npm install`/`npm i`/`npm ci`/`npx`; allows `.env.example`, `pnpm`, `uv`; blocks input it cannot parse. Standard library only. | Secrets by name only; `pnpm` and `uv` only |
| [`PERMISSIONS.md`](PERMISSIONS.md) and `../.claude/settings.json` | What agents may do, must never do, and which layer enforces it. The settings file holds deny rules only. | Defence in depth |

## Use with Claude Code

Prerequisites: `uv` 0.12.24 and `python3` on the PATH. From the repository root:

```
cd agent-pack && uv sync --locked && cd ..
claude plugin marketplace add ./agent-pack
claude plugin install supplier-iscan-pack@supplier-iscan-local
```

A fresh session started in the clone then lists the skill (`/skills`), the MCP server (`/mcp`) and the hook
(`/hooks`). Run Claude Code from the repository root: the MCP server reads `openapi.yaml` of the working directory.
Approve the MCP server when Claude Code asks; the pack grants no permission by itself.

## Use with another agent tool (Gemini CLI or Codex CLI)

Only two parts are portable:

- **Skill:** it is a plain `SKILL.md` (Markdown with `name` and `description` front matter). Copy or link
  `skills/evidence-wording/` into the tool's skills folder (Gemini CLI: `~/.gemini/skills/` or `.gemini/skills/`;
  Codex CLI: `.agents/skills/`), or reference the file from the tool's context file.
- **MCP server:** it uses the standard stdio configuration. Gemini CLI, `.gemini/settings.json`:

  ```json
  { "mcpServers": { "supplier-iscan-contract": {
      "command": "uv",
      "args": ["run", "--locked", "--project", "agent-pack", "python", "agent-pack/mcp_server/server.py"] } } }
  ```

  Codex CLI, `~/.codex/config.toml`:

  ```toml
  [mcp_servers.supplier-iscan-contract]
  command = "uv"
  args = ["run", "--locked", "--project", "agent-pack", "python", "agent-pack/mcp_server/server.py"]
  ```

  Start the tool from the repository root (relative paths).

**Claude Code only:** the plugin packaging (`.claude-plugin/`, the marketplace file), the hook wiring
(`hooks/hooks.json`; `hooks/guard.py` itself is a plain script reading the Claude Code hook JSON on stdin) and
`../.claude/settings.json`. With another tool, the rules they enforce rest on `AGENTS.md` and the owner's review.
These instructions for Gemini CLI and Codex CLI follow their documented formats and were not run here.

## Tests

`make test` runs the pack's tests (hook fixtures, MCP server against a temporary contract file, no network);
`make lint` runs `ruff` and `mypy` on it. The pack is its own `uv` project (`pyproject.toml`, `uv.lock`) with
`mcp` 2.3.0 and `pyyaml` 6.0.3 (`_docs/process/approved-dependencies.md`); it is never part of an image. It
contains no secret, no personal data and no `.env` file.
