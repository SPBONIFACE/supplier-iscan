"""PreToolUse guard for Claude Code (standard library only).

Reads the hook JSON on stdin. Exit 0 allows; exit 2 blocks and the message on stderr goes to the
agent. Rules (AGENTS.md):
  1. Never read, edit or write a .env file at any depth (.env, backend/.env, .env.local, ...),
     directly or through a shell command. .env.example is allowed.
  2. Never `npm install`, `npm i`, `npm ci` or `npx`, alone, in a pipeline or after `&&`.
     Use `pnpm` (`pnpm install`, `pnpm exec`) and `uv` (`uv run`).
Input the script cannot parse is blocked, never allowed.
"""

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
PARSE_RULE = "Blocked: the hook input could not be parsed, so it cannot be checked."

ENV_NAME = re.compile(r"^\.env([.*?\[].*)?$")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
OPERATORS = re.compile(r"^[();<>|&]+$")
NPM_BLOCKED = {"install", "i", "in", "ins", "inst", "add", "ci", "clean-install", "it", "cit"}
WRAPPERS = {"sudo", "env", "command", "exec", "time", "nohup", "nice", "xargs", "builtin"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
PATH_KEYS = ("file_path", "path", "notebook_path", "pattern", "glob")


class Block(Exception):
    pass


def is_env_name(value: str) -> bool:
    """True for .env, .env.local, backend/.env, .env* ...; False for .env.example."""
    base = value.strip().rstrip("/").rsplit("/", 1)[-1]
    return base != ".env.example" and ENV_NAME.match(base) is not None


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


def check_command(command: str, depth: int = 0) -> None:
    if depth > 3:
        raise Block(PARSE_RULE)
    # Newlines and backticks separate commands; replacing them inside quotes is harmless here.
    flat = command.replace("\n", " ; ").replace("`", " ( ")
    lexer = shlex.shlex(flat, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError as exc:
        raise Block(PARSE_RULE) from exc

    for tok in tokens:
        if OPERATORS.match(tok):
            continue
        for part in re.split(r"[=:,]", tok) + [tok]:
            if is_env_name(part):
                raise Block(ENV_RULE)

    for segment in split_segments(tokens):
        args = list(segment)
        while args and (ASSIGNMENT.match(args[0]) or args[0].rsplit("/", 1)[-1] in WRAPPERS):
            args.pop(0)
        if not args:
            continue
        cmd = args[0].rsplit("/", 1)[-1]
        rest = args[1:]
        if cmd == "npx":
            raise Block(NPM_RULE)
        if cmd == "npm":
            sub = next((a for a in rest if not a.startswith("-")), None)
            if sub in NPM_BLOCKED:
                raise Block(NPM_RULE)
        if cmd in SHELLS or cmd == "eval":
            if cmd == "eval":
                check_command(" ".join(rest), depth + 1)
            elif "-c" in rest and rest.index("-c") + 1 < len(rest):
                check_command(rest[rest.index("-c") + 1], depth + 1)


def check(payload: object) -> None:
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
