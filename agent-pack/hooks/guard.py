"""PreToolUse guard for Claude Code (standard library only).

Reads the hook JSON on stdin. Exit 0 allows; exit 2 blocks and the message on stderr goes to the
agent. Rules (AGENTS.md):
  1. Never read, edit or write a .env file at any depth (.env, backend/.env, .env.local, ...),
     directly or through a shell command. .env.example is allowed.
  2. Never `npm install`, `npm i`, `npm ci` or `npx`, alone, in a pipeline or after `&&`.
     Use `pnpm` (`pnpm install`, `pnpm exec`) and `uv` (`uv run`).
  3. Never add or upgrade a dependency from the command line: `uv add`, `uv pip install`,
     `pip install`, `pnpm add`, `pnpm install <package>`, `pnpm i <package>`,
     `pnpm up|update|upgrade`, alone, in a pipeline, after `&&` or through the wrappers below.
     `pnpm install` without a package and `uv sync` stay allowed
     (`make install`). New dependencies are the owner's decision.
  4. Only the owner changes `_docs/process/approved-dependencies.md`. An Edit, Write, MultiEdit or
     NotebookEdit of it, or a shell command that writes it (redirection, `tee`, `cp`, `mv`,
     `sed -i`, an interpreter, `git checkout`, ...), is blocked (exit 2) in every session, the
     orchestrator's included: a hook "ask" did not stop a sub-agent. The file name is matched
     wherever it is (any worktree, absolute or relative path). Reading it stays allowed. The
     owner's step, `make approve-dependency` (agent-pack/scripts/approve_dependency.py), is
     blocked for agents too, also through wrappers; the owner runs it in their own terminal.
     There is no bypass by environment variable.
  5. Never read secrets from the macOS Keychain or another OS secret store: `security`
     (find-generic-password, find-internet-password, find-certificate -p, dump-keychain, export,
     unlock-keychain), `secret-tool lookup`, `pass show`, `gopass show`, `op read`, `op item get`,
     `bw get`; and never call the key loader `iscan-keys`. Same reach as the other rules
     (pipelines, `&&`, subshells, wrappers, `-c`). `security list-keychains` and
     `security find-certificate` without -p stay allowed.
Input the script cannot parse is blocked, never allowed.
"""

from __future__ import annotations  # the hook also starts under an older system python3

import json
import re
import shlex
import sys
from typing import Any

ENV_RULE = (
    "Blocked: a .env file must never be read, edited or written (AGENTS.md: secrets are "
    "referenced by name only). Allowed: .env.example; ask the owner for anything else."
)
NPM_RULE = (
    "Blocked: npm install / npm i / npm ci / npx are not allowed (AGENTS.md: pnpm and uv only). "
    "Allowed: pnpm install, pnpm exec, uv run."
)
DEPENDENCY_RULE = (
    "Blocked: adding or upgrading a dependency from the command line is not allowed "
    "(AGENTS.md: no new dependency without asking). Stop and report the package you need "
    "to the owner. Allowed: pnpm install (no package), uv sync, make install."
)
LIST_RULE = (
    "Blocked: only the owner changes _docs/process/approved-dependencies.md (AGENTS.md: no new "
    "dependency without asking). Do not edit it, and do not run make approve-dependency. Stop "
    "and report the package and the exact version you need, and why. Reading the file is allowed."
)
KEYSTORE_RULE = (
    "Blocked: reading secrets from the OS keychain or a secret store, or calling the key loader "
    "(iscan-keys), is not allowed for agents. Stop. Ask the owner to run the command in their own "
    "terminal. Never ask for the key value itself."
)
PARSE_RULE = "Blocked: the hook input could not be parsed, so it cannot be checked."

ENV_NAME = re.compile(r"^\.env([.*?\[].*)?$")
ENV_EXAMPLE = re.compile(r"\.env\.example(?![a-z0-9_])")
ENV_LITERAL = re.compile(r"(?<![a-z0-9])\.env(?![a-z0-9_])")
NPM_VALUE_FLAGS = {  # options of npm that take a value in the next word
    "--prefix",
    "-c",
    "--workspace",
    "-w",
    "--registry",
    "--userconfig",
    "--globalconfig",
    "--cache",
    "--loglevel",
    "--otp",
    "--tag",
    "--scope",
}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
OPERATORS = re.compile(r"^[();<>|&]+$")
NPM_BLOCKED = {"install", "i", "in", "ins", "inst", "add", "ci", "clean-install", "it", "cit"}
WRAPPERS = {"sudo", "env", "command", "exec", "time", "nohup", "nice", "xargs", "builtin"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
SECURITY_READS = {
    "find-generic-password", "find-internet-password", "dump-keychain", "export",
    "unlock-keychain",
}  # fmt: skip
LOADER_NAME = "iscan-keys"
SHELL_C_FLAG = re.compile(r"^-[a-z]*c[a-z]*$")
LIST_NAME = "approved-dependencies.md"
APPROVE_NAME = "approve-dependency"  # make target and script (approve_dependency.py)
RUNNERS = {"make", "gmake", "uv", "uvx"}
PNPM_VALUE_FLAGS = {"--filter", "-f", "-c", "--dir", "--prefix", "--registry", "--reporter"}
PNPM_UPGRADES = {"up", "update", "upgrade"}
PNPM_INSTALLS = {"install", "i"}
UV_VALUE_FLAGS = {"--directory", "--project", "--python", "-p", "--config-file", "--cache-dir"}
PIP_NAME = re.compile(r"^pip[0-9.]*$")
PYTHON_NAME = re.compile(r"^python[0-9.]*$")
WRITERS = {  # commands that may write the file they are given
    "tee", "cp", "mv", "install", "rm", "truncate", "dd", "ed", "ex", "vi", "vim", "nano", "perl",
    "ruby", "node", "awk", "gawk", "patch", "ln", "rsync", "curl", "wget", "python", "python3",
}  # fmt: skip
GIT_WRITES = {
    "checkout",
    "restore",
    "apply",
    "stash",
    "reset",
    "revert",
    "merge",
    "rebase",
    "mv",
    "rm",
}
HEREDOC = re.compile(r"<<-?\s*(['\"])([A-Za-z_][A-Za-z0-9_]*)\1")
HEREDOC_RUNNERS = re.compile(
    r"[\s;&|(`](bash|sh|zsh|dash|ksh|python[0-9.]*|node|perl|ruby|eval|source|\.)\s"
)
PATH_KEYS = ("file_path", "path", "notebook_path", "pattern", "glob")


class Block(Exception):
    pass


def is_env_name(value: str) -> bool:
    """True for .env, .env.local, backend/.env, .env* ...; False for .env.example."""
    base = value.strip().rstrip("/").rsplit("/", 1)[-1].lower()
    return base != ".env.example" and ENV_NAME.match(base) is not None


def mentions_env_file(command: str) -> bool:
    """A literal .env file name anywhere in the string, interpreter strings included."""
    text = ENV_EXAMPLE.sub("", command.lower())
    return ENV_LITERAL.search(text) is not None


def check_paths(tool_input: dict[str, Any]) -> None:
    for key in PATH_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and is_env_name(value):
            raise Block(ENV_RULE)


def split_segments(tokens: list[str]) -> list[list[str]]:
    segments: list[list[str]] = [[]]
    for tok in tokens:
        if OPERATORS.match(tok):
            segments.append([])
        else:
            segments[-1].append(tok)
    return [s for s in segments if s]


def strip_heredocs(command: str) -> str:
    """Drop the body of a heredoc with a quoted delimiter: it is data (an issue or pull request
    text), not shell, and its apostrophes and quotes broke the tokenizer. A body fed to a shell or
    an interpreter (`bash <<'EOF'`) is kept, so it is still checked; so is the body of an unquoted
    delimiter, where the shell expands `$(...)`. .env names are still searched in the whole text."""
    out: list[str] = []
    end: str | None = None
    for line in command.split("\n"):
        if end is not None:
            if line.strip() == end:
                end = None
            continue
        out.append(line)
        match = HEREDOC.search(line)
        if match and not HEREDOC_RUNNERS.search(" " + line[: match.start()] + " "):
            end = match.group(2)
    return "\n".join(out)


def tokenize(command: str) -> list[str]:
    # Newlines and backticks separate commands; replacing them inside quotes is harmless here.
    flat = strip_heredocs(command).replace("\n", " ; ").replace("`", " ( ")
    lexer = shlex.shlex(flat, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError as exc:
        raise Block(PARSE_RULE) from exc


def check_command(command: str, depth: int = 0) -> None:
    if depth > 3:
        raise Block(PARSE_RULE)
    tokens = tokenize(command)

    if mentions_env_file(command):
        raise Block(ENV_RULE)
    for tok in tokens:
        if OPERATORS.match(tok):
            continue
        for part in re.split(r"[=:,]", tok) + [tok]:
            if is_env_name(part):
                raise Block(ENV_RULE)

    for tok in tokens:
        if "$(" in tok:  # a command substitution inside quotes
            check_command(tok.replace("$(", " ; ").replace(")", " ; "), depth + 1)

    for segment in split_segments(tokens):
        args = list(segment)
        while args and (ASSIGNMENT.match(args[0]) or args[0].rsplit("/", 1)[-1] in WRAPPERS):
            args.pop(0)
        if not args:
            continue
        check_argv(args, depth)


def npm_subcommand(rest: list[str]) -> str | None:
    """First non-option word, skipping the values of options such as --prefix x or -C x."""
    it = iter(rest)
    for arg in it:
        if arg.startswith("-"):
            if arg.lower() in NPM_VALUE_FLAGS:
                next(it, None)
            continue
        return arg
    return None


def positional_words(rest: list[str], value_flags: set[str]) -> list[str]:
    """Words that are not options, skipping the value of options such as --filter x."""
    words: list[str] = []
    it = iter(rest)
    for arg in it:
        if arg.startswith("-"):
            if arg.lower() in value_flags:
                next(it, None)
            continue
        words.append(arg)
    return words


def check_argv(args: list[str], depth: int) -> None:
    if depth > 3 or not args:
        return
    cmd = args[0].rsplit("/", 1)[-1]
    rest = args[1:]
    if runs_approval(cmd, rest):
        raise Block(LIST_RULE)
    if reads_secret_store(cmd, rest):
        raise Block(KEYSTORE_RULE)
    if cmd == "npx":
        raise Block(NPM_RULE)
    if cmd == "npm" and npm_subcommand(rest) in NPM_BLOCKED:
        raise Block(NPM_RULE)
    if cmd == "corepack":
        check_argv(rest, depth + 1)
    if cmd == "pnpm":
        words = positional_words(rest, PNPM_VALUE_FLAGS)
        if words[:1] in (["exec"], ["dlx"]):
            check_argv(rest[rest.index(words[0]) + 1 :], depth + 1)
        if words[:1] and (words[0] == "add" or words[0] in PNPM_UPGRADES):
            raise Block(DEPENDENCY_RULE)
        if words[:1] and words[0] in PNPM_INSTALLS and len(words) > 1:
            raise Block(DEPENDENCY_RULE)
    if cmd == "uv":
        words = positional_words(rest, UV_VALUE_FLAGS)
        if words[:1] == ["add"] or words[:2] == ["pip", "install"]:
            raise Block(DEPENDENCY_RULE)
        if words[:1] == ["run"]:  # uv run pip install x, uv run python -m pip install x
            sub = rest[rest.index("run") + 1 :]
            while sub and sub[0].startswith("-"):
                sub = sub[1:]
            check_argv(sub, depth + 1)
    if PIP_NAME.match(cmd) and "install" in positional_words(rest, set())[:1]:
        raise Block(DEPENDENCY_RULE)
    if PYTHON_NAME.match(cmd) and rest[:2] == ["-m", "pip"]:
        check_argv(rest[1:], depth + 1)
    if cmd == "eval":
        check_command(" ".join(rest), depth + 1)
    elif cmd in SHELLS:
        flags = [i for i, a in enumerate(rest) if SHELL_C_FLAG.match(a)]
        if flags and flags[0] + 1 < len(rest):
            check_command(rest[flags[0] + 1], depth + 1)


def reads_secret_store(cmd: str, rest: list[str]) -> bool:
    """True for a command that reads a secret from an OS secret store, or the key loader."""
    words = positional_words(rest, set())
    if cmd == LOADER_NAME:
        return True
    if cmd == "security":
        if words[:1] == ["find-certificate"]:
            return any(re.match(r"^-[a-zA-Z]*p[a-zA-Z]*$", a) for a in rest)
        return words[:1] != [] and words[0] in SECURITY_READS
    if cmd == "secret-tool":
        return words[:1] == ["lookup"]
    if cmd in {"pass", "gopass"}:
        return words[:1] == ["show"]
    if cmd == "op":
        return words[:1] == ["read"] or words[:2] == ["item", "get"]
    if cmd == "bw":
        return words[:1] == ["get"]
    return False


def runs_approval(cmd: str, rest: list[str]) -> bool:
    """True for the owner's approval step: the make target or the script, run by name."""

    def names_it(word: str) -> bool:
        return APPROVE_NAME in word.lower().replace("_", "-")

    if names_it(cmd):
        return True
    return (cmd in RUNNERS or PYTHON_NAME.match(cmd) is not None) and any(names_it(a) for a in rest)


def is_list_name(value: str) -> bool:
    return value.strip().rstrip("/").rsplit("/", 1)[-1].lower() == LIST_NAME


def command_writes_list(command: str, depth: int = 0) -> bool:
    """True when a command line writes the approved-dependencies list: a redirection onto it, or a
    segment that names it and runs a command able to write (tee, cp, mv, sed -i, an interpreter,
    git checkout ...). Reading it (cat, grep, git diff) and mentioning it in a pull request text
    are not writes. Obfuscated names (a glob, a variable) are not caught."""
    if depth > 3 or LIST_NAME not in command.lower():
        return False
    tokens = tokenize(command)
    for i, tok in enumerate(tokens):
        if ">" in tok and OPERATORS.match(tok):
            # `> file` or `>> file`; the target may also be glued to the operator.
            nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
            if is_list_name(nxt):
                return True
    for segment in split_segments(tokens):
        args = list(segment)
        while args and (ASSIGNMENT.match(args[0]) or args[0].rsplit("/", 1)[-1] in WRAPPERS):
            args.pop(0)
        if not args:
            continue
        cmd, rest = args[0].rsplit("/", 1)[-1], args[1:]
        if cmd in SHELLS and "-c" in rest and rest.index("-c") + 1 < len(rest):
            if command_writes_list(rest[rest.index("-c") + 1], depth + 1):
                return True
        if not any(LIST_NAME in a.lower() for a in rest):
            continue  # this segment does not name the file
        if cmd in {"sed", "gsed"}:
            if any(re.match(r"^(-[a-zA-Z]*i|--in-place)", a) for a in rest):
                return True
        elif cmd == "git":
            sub = positional_words(rest, {"-C", "-c"})[:1]
            if sub and sub[0] in GIT_WRITES:
                return True
        elif cmd in WRITERS or PYTHON_NAME.match(cmd) or cmd in {"uv", "uvx"}:
            return True
    return False


def writes_list(payload: dict[str, Any]) -> bool:
    tool_input = payload["tool_input"]
    if payload["tool_name"] in {"Edit", "Write", "MultiEdit", "NotebookEdit"}:
        return any(
            isinstance(tool_input.get(k), str) and is_list_name(tool_input[k])
            for k in ("file_path", "path", "notebook_path")
        )
    command = tool_input.get("command")
    return (
        payload["tool_name"] == "Bash" and isinstance(command, str) and command_writes_list(command)
    )


def check(payload: object) -> None:
    """Raise Block to refuse; return when the call is allowed."""
    if not isinstance(payload, dict):
        raise Block(PARSE_RULE)
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_name, str) or not isinstance(tool_input, dict):
        raise Block(PARSE_RULE)
    check_paths(tool_input)
    if tool_name == "Bash":
        command = tool_input.get("command")
        if not isinstance(command, str):
            raise Block(PARSE_RULE)
        check_command(command)
    if writes_list(payload):
        raise Block(LIST_RULE)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
        check(payload)
    except Block as block:
        print(block, file=sys.stderr)
        return 2
    except Exception:  # noqa: BLE001 - anything unexpected is a block, never an allow
        print(PARSE_RULE, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
