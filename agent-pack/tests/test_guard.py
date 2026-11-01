"""Hook tests: fixture inputs only; no real .env file is created or read."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

GUARD = Path(__file__).resolve().parents[1] / "hooks" / "guard.py"


def run(stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, "-I", str(GUARD)], input=stdin, capture_output=True, text=True, check=False
    )


def bash(command: str) -> str:
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})


def tool(name: str, **tool_input: str) -> str:
    return json.dumps({"tool_name": name, "tool_input": tool_input})


BLOCKED_ENV = [
    tool("Read", file_path="/repo/.env"),
    tool("Read", file_path="/repo/backend/.env"),
    tool("Edit", file_path=".env.local", old_string="a", new_string="b"),
    tool("Write", file_path="frontend/.env.production", content="x"),
    tool("Grep", pattern="KEY", path="/repo/backend/.env"),
    tool("Glob", pattern="**/.env*"),
    bash("cat .env"),
    bash("cat backend/.env"),
    bash("source .env"),
    bash(". ./.env"),
    bash("head -3 ./backend/.env.local"),
    bash("echo hi > .env"),
    bash("grep KEY < .env"),
    bash("set -a; source .env; set +a"),
    bash("cat .env*"),
    bash("echo $(cat .env)"),
    bash("echo `cat .env`"),
    bash("ls && cat .env"),
    bash("bash -c 'cat .env'"),
    bash("cp .env /tmp/x"),
    bash("docker run --env-file=.env x"),
]
BLOCKED_NPM = [
    bash("npm install"),
    bash("npm i left-pad"),
    bash("npm ci"),
    bash("npm --silent install x"),
    bash("npx prettier ."),
    bash("pnpm test && npm install"),
    bash("echo x | npx foo"),
    bash("cd frontend; npm i"),
    bash("FOO=1 npm ci"),
    bash("sudo npm install -g x"),
    bash("sh -c 'npx foo'"),
    bash("cd a\nnpm install"),
    bash("(npm i)"),
    bash("/usr/bin/npx foo"),
]
UNPARSEABLE = [
    "",
    "not json",
    "[]",
    "null",
    "{}",
    json.dumps({"tool_name": "Bash"}),
    json.dumps({"tool_name": "Bash", "tool_input": "cat x"}),
    json.dumps({"tool_name": "Bash", "tool_input": {}}),
    json.dumps({"tool_name": 3, "tool_input": {}}),
    bash("echo 'unclosed"),
]
ALLOWED = [
    tool("Read", file_path="/repo/.env.example"),
    tool("Read", file_path="/repo/backend/.env.example"),
    tool("Edit", file_path="README.md", old_string="a", new_string="b"),
    tool("Read", file_path="/repo/docs/environment.md"),
    tool("Read", file_path="/repo/.envrc.md"),
    bash("cat .env.example"),
    bash("cp .env.example /tmp/x"),
    bash("pnpm install"),
    bash("pnpm install --frozen-lockfile"),
    bash("pnpm exec vitest"),
    bash("uv run pytest"),
    bash("cd backend && uv run --locked pytest"),
    bash("make test"),
    bash("gh issue view 56"),
    bash("git add .env.example"),
    bash("echo 'a;b|c' && ls"),
    bash("echo npm install"),
    bash("pnpm dlx x"),
    bash("npm --version"),
    tool("WebFetch", url="https://example.org"),
]


@pytest.mark.parametrize("stdin", BLOCKED_ENV)
def test_env_access_blocked(stdin: str) -> None:
    result = run(stdin)
    assert result.returncode == 2, stdin
    assert ".env" in result.stderr
    assert ".env.example" in result.stderr  # the allowed alternative is named


@pytest.mark.parametrize("stdin", BLOCKED_NPM)
def test_npm_blocked(stdin: str) -> None:
    result = run(stdin)
    assert result.returncode == 2, stdin
    assert "pnpm" in result.stderr
    assert "uv run" in result.stderr


@pytest.mark.parametrize("stdin", UNPARSEABLE)
def test_unparseable_blocked(stdin: str) -> None:
    result = run(stdin)
    assert result.returncode == 2, stdin
    assert "could not be parsed" in result.stderr


@pytest.mark.parametrize("stdin", ALLOWED)
def test_allowed(stdin: str) -> None:
    result = run(stdin)
    assert result.returncode == 0, (stdin, result.stderr)
    assert result.stderr == ""
