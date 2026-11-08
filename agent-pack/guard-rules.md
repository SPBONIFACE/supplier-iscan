# Guard rules: project-specific or useful everywhere

`hooks/guard.py` checks every tool call of a coding agent before it runs and refuses some of them. This note sorts
its rules into two groups. Some only make sense in Supplier iScan. Others are worth having on the whole machine, as
a global hook. It is the starting point for that global hook.

Note: while the plugin is installed globally, the hook runs from this repository's working copy. Whichever branch is
checked out here is the guard that every project gets.

## Useful on the whole machine

| Rule | What it blocks | Notes for a global hook |
|---|---|---|
| `.env` files | Reading, editing, writing or searching a `.env` file (`.env`, `.env.local`, `backend/.env`, `.env*`), by any tool or in any command, including inside a heredoc or a program given to an interpreter. `.env.example` is allowed. | Generic as it is. |
| OS secret stores | `security find-generic-password` / `find-internet-password` / `dump-keychain` / `export` / `unlock-keychain`, `security find-certificate -p`, `secret-tool lookup`, `pass show`, `gopass show`, `op read`, `op item get`, `bw get`. | Generic as it is. |
| Key loader | Calling the shell function that loads API keys from the Keychain (`iscan-keys`). | The idea is general, but the name is this project's. A global hook should take a list of loader names. |
| Adding or upgrading a dependency | `pip install`, `python -m pip install`, `uv add`, `uv pip install`, `uv run pip install`, `pnpm add`, `pnpm up` / `update` / `upgrade`, `pnpm install <package>`, also through `pnpm exec`, `pnpm dlx` and `corepack`. Installing from a lockfile (`uv sync`, `pnpm install`, `make install`) stays allowed. | Generic, but a different project may need another way to approve a package. The message points to "the owner". |
| npm and npx | `npm install` / `i` / `ci` / `add` (and their aliases), `npx`. | Overlaps with the existing global `~/.claude/hooks/block-npm.py`. Keep one of the two. |
| Fail closed | A call the guard cannot read (malformed input, a command it cannot tokenize) is refused, never allowed. | Generic: keep it in any global hook. |
| Wrappers and nesting | The rules also apply through `sudo`, `env`, `command`, `exec`, `xargs`, `bash -c`, `sh -c`, `eval`, `$(...)` and a heredoc fed to a shell or an interpreter. | Generic. |

## Specific to Supplier iScan

| Rule | What it blocks | Why it is project-specific |
|---|---|---|
| Approved-dependencies list | Any edit or write of `_docs/process/approved-dependencies.md`, by a file tool or a command (redirection, `tee`, `cp`, `sed -i`, `git checkout`, an interpreter program naming it). Reading it is allowed. | The file and the approval process are this project's. |
| Approval step | Running `make approve-dependency` or `scripts/approve_dependency.py`. | It is the owner's step in this project. |
| `iscan-keys` | The key loader by name (see above). | The name is this project's. |

## How a program given to an interpreter is checked

A command such as `python3 - <<'EOF' … EOF` feeds a program to Python. The program is not shell, so the guard does
not run it through the shell tokenizer, where an apostrophe in its text would read as an unclosed quote. Instead
it reads every word of the program and treats each one as a possible command start. A command written inside a
string, such as `os.system('pip install x')` or `["uv", "add", "x"]`, is still caught. A program that names the
approved-dependencies list is treated as a write.
