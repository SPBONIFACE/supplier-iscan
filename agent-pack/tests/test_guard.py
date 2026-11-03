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
    bash("python3 -c \"open('.env')\""),
    bash("node -e \"require('fs').readFileSync('backend/.env')\""),
    bash("cat .ENV"),
    bash("cat Backend/.Env.Local"),
    tool("Read", file_path="/repo/.ENV"),
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
    bash("npm --prefix x i"),
    bash("npm -C x ci"),
    bash("npm --prefix=x install"),
    bash("corepack npm install"),
    bash("pnpm exec npm install"),
    bash("pnpm dlx npm i"),
    bash("pnpm exec npx foo"),
    bash("NPM_CONFIG_X=1 npm --silent -w a install"),
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
    bash("npm --prefix x run build"),
    bash("python3 -c \"print('.env.example')\""),
    bash("cat docs/.environment.md prod.env.md"),
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


BLOCKED_DEPENDENCY = [
    bash("uv add protobuf"),
    bash("cd backend && uv add --dev x"),
    bash("uv pip install x"),
    bash("uv --directory backend add x"),
    bash("uv run pip install x"),
    bash("uv run --locked python -m pip install x"),
    bash("pip install x"),
    bash("pip3 install -r requirements.txt"),
    bash("python3 -m pip install x"),
    bash("/usr/bin/pip install x"),
    bash("pnpm add react"),
    bash("pnpm -C frontend add -D x"),
    bash("pnpm --filter web add x"),
    bash("pnpm install left-pad"),
    bash("pnpm i left-pad"),
    bash("pnpm install -D x"),
    bash("pnpm up --latest"),
    bash("pnpm update"),
    bash("pnpm upgrade -L"),
    bash("make test && pnpm add x"),
    bash("echo hi | pip install x"),
    bash("sudo pip install x"),
    bash("sh -c 'uv add x'"),
    bash("corepack pnpm add x"),
    bash("pnpm exec pip install x"),
    bash("cd a\nuv add x"),
    bash("FOO=1 uv add x"),
]
ALLOWED_DEPENDENCY = [
    bash("uv sync"),
    bash("uv sync --locked"),
    bash("uv lock --check"),
    bash("uv run --locked pytest"),
    bash("uv pip list"),
    bash("pip --version"),
    bash("pip list"),
    bash("pnpm install"),
    bash("pnpm install --frozen-lockfile"),
    bash("pnpm -C frontend install --frozen-lockfile"),
    bash("pnpm i"),
    bash("pnpm test"),
    bash("make install"),
    bash("echo 'uv add x'"),
    bash("gh pr create --title 'uv add is blocked' --body 'pnpm add x'"),
]
LIST = "_docs/process/approved-dependencies.md"
BLOCKED_LIST = [
    tool("Edit", file_path=f"/repo/{LIST}", old_string="a", new_string="b"),
    tool("Write", file_path=LIST, content="x"),
    tool("MultiEdit", file_path=f"/repo/{LIST}"),
    tool("NotebookEdit", notebook_path=LIST),
    tool("Edit", file_path=f"/r/.claude/worktrees/agent-x/{LIST}", old_string="a", new_string="b"),
    bash(f"echo x >> /r/.claude/worktrees/agent-x/{LIST}"),
    bash(f"cp /tmp/x /abs/path/{LIST}"),
    bash("make approve-dependency PACKAGE=x VERSION=1.0.0 SCOPE=dev NOTE=y"),
    bash("cd /repo && make -s approve-dependency PACKAGE=x"),
    bash("bash -c 'make approve-dependency PACKAGE=x'"),
    bash("env FOO=1 make approve-dependency PACKAGE=x"),
    bash("python3 agent-pack/scripts/approve_dependency.py --package x"),
    bash("uv run python scripts/approve_dependency.py --package x"),
    bash("./agent-pack/scripts/approve_dependency.py --package x"),
    bash(f"echo '| x |' >> {LIST}"),
    bash(f"cat new > {LIST}"),
    bash(f"cat new >{LIST}"),
    bash(f"printf x | tee -a {LIST}"),
    bash(f"sed -i 's/a/b/' {LIST}"),
    bash(f"sed -ni 's/a/b/p' {LIST}"),
    bash(f"cp /tmp/x {LIST}"),
    bash(f"mv /tmp/x {LIST}"),
    bash(f"git checkout origin/main -- {LIST}"),
    bash(f"python3 -c \"open('{LIST}', 'w').write('x')\""),
    bash(f"uv run python -c \"open('{LIST}', 'a')\""),
    bash(f"bash -c 'echo x >> {LIST}'"),
    bash(f"cd repo && perl -pi -e 's/a/b/' {LIST}"),
]
ALLOWED_LIST = [
    tool("Read", file_path=f"/repo/{LIST}"),
    tool("Grep", pattern="pypdf", path=LIST),
    tool("Edit", file_path="_docs/process/process.md", old_string="a", new_string="b"),
    bash(f"cat {LIST}"),
    bash(f"grep -n protobuf {LIST}"),
    bash(f"sed -n '1,5p' {LIST}"),
    bash(f"git diff origin/main -- {LIST}"),
    bash(f"git add {LIST}"),
    bash(f"wc -l {LIST} > /tmp/count"),
    bash(f"gh pr create --title 'x' --body 'Changes {LIST}'"),
    bash("gh pr create --title 'x' --body 'Use make approve-dependency'"),
    bash("grep -rn approve-dependency Makefile"),
    bash("make install"),
    bash("uv sync --locked"),
    tool("Write", file_path="agent-pack/scripts/other.py", content="x"),
]
# Legitimate long commands: a quote or an apostrophe in the text must not block.
HEREDOCS = [
    "gh issue create --body \"$(cat <<'EOF'\nIt doesn't fail; 5\" pipe, `code`.\nEOF\n)\"",
    "gh pr create --body-file - <<'EOF'\nIt's done and the owner's call.\nEOF",
    "git commit -m \"$(cat <<'EOF'\nfix: don't crash\n\nCo-Authored-By: X\nEOF\n)\"",
    "cat > /tmp/note.md <<'EOF'\nuv add protobuf is blocked; it's a rule\nEOF\nls",
]
HEREDOC_STILL_CHECKED = [
    "bash <<'EOF'\nnpm install\nEOF",  # the body is a script: checked
    "cat <<EOF\n$(npm install)\nEOF",  # unquoted delimiter: the shell expands it
    "cat <<'EOF'\nok\nEOF\nnpm install",  # a command after the body
    "cat <<'EOF'\nsecret\nEOF\ncat .env",
    "cat <<'EOF'\nit's\nEOF\nuv add x",
    "gh issue create --body-file - <<'EOF'\ncat .env\nEOF",  # a .env name in the text
]


@pytest.mark.parametrize("stdin", BLOCKED_DEPENDENCY)
def test_dependency_change_blocked(stdin: str) -> None:
    result = run(stdin)
    assert result.returncode == 2, stdin
    assert "dependency" in result.stderr
    assert "owner" in result.stderr


@pytest.mark.parametrize("stdin", ALLOWED_DEPENDENCY)
def test_dependency_install_still_allowed(stdin: str) -> None:
    result = run(stdin)
    assert result.returncode == 0, (stdin, result.stderr)
    assert result.stdout == ""


@pytest.mark.parametrize("stdin", BLOCKED_LIST)
def test_approved_list_write_is_blocked(stdin: str) -> None:
    result = run(stdin)
    assert result.returncode == 2, stdin
    assert result.stdout == ""
    assert "only the owner" in result.stderr
    assert "report" in result.stderr


@pytest.mark.parametrize("stdin", ALLOWED_LIST)
def test_approved_list_read_is_allowed(stdin: str) -> None:
    result = run(stdin)
    assert result.returncode == 0, (stdin, result.stderr)
    assert result.stdout == ""


def test_no_environment_variable_bypass() -> None:
    env = {"CLAUDE_OWNER": "1", "ALLOW_LIST_EDIT": "1", "OWNER": "1"}
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-I", str(GUARD)],
        input=tool("Write", file_path=LIST, content="x"),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 2


@pytest.mark.parametrize("command", HEREDOCS)
def test_heredoc_text_is_not_parsed_as_shell(command: str) -> None:
    result = run(bash(command))
    assert result.returncode == 0, (command, result.stderr)
    assert result.stdout == ""


@pytest.mark.parametrize("command", HEREDOC_STILL_CHECKED)
def test_heredoc_does_not_hide_commands(command: str) -> None:
    assert run(bash(command)).returncode == 2, command


def test_truly_unparseable_stays_blocked() -> None:
    result = run(bash("echo \"unclosed $(cat <<'EOF'\nfine\nEOF\n"))
    assert result.returncode == 2
    assert "could not be parsed" in result.stderr
