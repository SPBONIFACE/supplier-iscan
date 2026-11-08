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
# A program given to an interpreter on standard input: its text is not shell, so an apostrophe
# in it must not block (regression: "Panos's" in a Python string failed closed as unparseable).
INTERPRETER_HEREDOCS = [
    "python3 - <<'EOF'\nprint(\"Panos's notes on Argon's results\")\nEOF",
    "cd /tmp && python3 - <<'EOF'\nnote = \"it's Argon's turn\"\nprint(note)\nEOF\nls",
    'python3 - <<EOF\nprint("Panos\'s")\nEOF',
    "node <<'EOF'\nconsole.log(\"it's fine\")\nEOF",
    "uv run python - <<'EOF'\nprint(\"don't\")\nEOF",
    "python3 - <<'EOF'\nopen('.env.example').read()  # it's allowed\nEOF",
]
# The same kind of program, with something forbidden in it: still blocked.
INTERPRETER_HEREDOC_BLOCKED = [
    "python3 - <<'EOF'\nprint(\"Panos's\")\nopen('.env').read()\nEOF",
    'python3 - <<\'EOF\'\nprint("Argon\'s")\nopen("backend/.env.local")\nEOF',
    "python3 - <<'EOF'\nimport os\nos.system('pip install x')  # Panos's\nEOF",
    'python3 - <<\'EOF\'\nimport subprocess\nsubprocess.run(["uv", "add", "x"])\nEOF',
    'python3 - <<\'EOF\'\nimport subprocess\nsubprocess.run(["pnpm", "add", "x"])\nEOF',
    "python3 - <<'EOF'\nimport subprocess\nsubprocess.run(['npm', 'install'])\nEOF",
    "python3 - <<'EOF'\nimport os\nos.system(\"python -m pip install x\")\nEOF",
    "python3 - <<'EOF'\nimport os\nos.system('security find-generic-password -s k -w')\nEOF",
    "python3 - <<'EOF'\nimport os\nos.system(\"bash -c 'iscan-keys'\")\nEOF",
    "python3 - <<'EOF'\nimport os\nos.system('make approve-dependency PACKAGE=x')\nEOF",
    "python3 - <<'EOF'\np = '_docs/process/approved-dependencies.md'\nopen(p, 'a').write('x')\nEOF",
    "python3 - <<'EOF'\nprint(\"it's\")\nEOF\nuv add x",  # a command after the body
    "python3 - <<'EOF'\nprint(1)\npip install x",  # no closing delimiter
]
# A heredoc-like text in a quoted message (no closing delimiter): read as shell, as before.
INTERPRETER_HEREDOC_MENTIONED = [
    'git commit -m "fix: python3 - <<EOF ... EOF was blocked\n\nbody line"',
    "gh pr create --body \"Problem: \\`python3 - <<'EOF' ... EOF\\` was blocked\nSecond line\"",
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


@pytest.mark.parametrize("command", INTERPRETER_HEREDOCS)
def test_interpreter_heredoc_text_is_not_parsed_as_shell(command: str) -> None:
    result = run(bash(command))
    assert result.returncode == 0, (command, result.stderr)
    assert result.stdout == ""


@pytest.mark.parametrize("command", INTERPRETER_HEREDOC_BLOCKED)
def test_interpreter_heredoc_is_still_checked(command: str) -> None:
    result = run(bash(command))
    assert result.returncode == 2, command
    assert "could not be parsed" not in result.stderr, (command, result.stderr)


@pytest.mark.parametrize("command", INTERPRETER_HEREDOC_MENTIONED)
def test_heredoc_named_in_a_message_is_allowed(command: str) -> None:
    result = run(bash(command))
    assert result.returncode == 0, (command, result.stderr)


def test_unclosed_interpreter_heredoc_with_apostrophe_stays_blocked() -> None:
    assert run(bash("python3 - <<'EOF'\nprint(\"it's\")\npip install x")).returncode == 2


def test_truly_unparseable_stays_blocked() -> None:
    result = run(bash("echo \"unclosed $(cat <<'EOF'\nfine\nEOF\n"))
    assert result.returncode == 2
    assert "could not be parsed" in result.stderr


BLOCKED_SECRET = [
    bash(c)
    for c in [
        "security find-generic-password -s anthropic -w",
        "security -q find-generic-password -a me -w",
        "/usr/bin/security find-internet-password -s x -w",
        "security find-certificate -p -c Name",
        "security find-certificate -ap",
        "security dump-keychain -d login.keychain",
        "security export -k login.keychain -t privKeys",
        "security unlock-keychain -p x login.keychain",
        "secret-tool lookup service iscan",
        "pass show provider/key",
        "gopass show provider/key",
        "op read op://vault/item/field",
        "op item get iscan --fields key",
        "bw get password iscan",
        "iscan-keys",
        "iscan-keys && make run",
        "security find-generic-password -w | pbcopy",
        "true && security find-generic-password -w",
        "echo $(security find-generic-password -w)",
        'echo "$(security find-generic-password -w)"',
        "X=`security find-generic-password -w`",
        "(security dump-keychain)",
        "sudo security find-generic-password -w",
        "env FOO=1 security find-generic-password -w",
        "xargs security find-generic-password",
        "uv run security find-generic-password -w",
        "pnpm exec security find-generic-password -w",
        "zsh -c 'security find-generic-password -w'",
        "bash -c 'op read op://v/i/f'",
        "bash -lc 'iscan-keys; make run'",
        "zsh -ic iscan-keys",
        "sh -c \"bash -c 'pass show a'\"",
        "eval 'bw get password x'",
        "nohup iscan-keys",
    ]
]
ALLOWED_SECRET = [
    bash(c)
    for c in [
        "security list-keychains",
        "security find-certificate -c Name",
        "security find-identity -v",
        "security help",
        "cat ~/.zshrc",
        "grep -n iscan ~/.zshrc",
        "pass ls",
        "op --version",
        "bw status",
        "secret-tool store --label x",
        "zsh -c 'echo hello'",
    ]
]


@pytest.mark.parametrize("stdin", BLOCKED_SECRET)
def test_secret_store_read_blocked(stdin: str) -> None:
    result = run(stdin)
    assert result.returncode == 2
    assert "own terminal" in result.stderr
    assert "Sandra" not in result.stderr


@pytest.mark.parametrize("stdin", ALLOWED_SECRET)
def test_secret_free_commands_allowed(stdin: str) -> None:
    assert run(stdin).returncode == 0
