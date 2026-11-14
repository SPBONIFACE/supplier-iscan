"""Cloud Run worker pools refuse secret volume mounts ("Secrets volume mount is not supported for
Worker Pools yet"), so the deploy must never pass a content-file mount to the worker pool."""

import re
import subprocess
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[3] / "deploy" / "deploy.sh"


def _worker_deploy_command() -> str:
    text = DEPLOY.read_text(encoding="utf-8")
    match = re.search(r"beta run worker-pools deploy .*?(?:\n\s*\n|\Z)", text, re.DOTALL)
    assert match, "no worker-pools deploy command in deploy.sh"
    return match.group(0)


def test_worker_pool_gets_no_content_file_mounts() -> None:
    command = _worker_deploy_command()
    assert '"$work/worker.yaml"' in command
    assert "$worker_extra" in command
    assert '"$work/app.yaml"' not in command
    assert "$extra" not in command.replace("$worker_extra", "")


def test_worker_secrets_are_fixed_before_the_content_mounts_are_added() -> None:
    text = DEPLOY.read_text(encoding="utf-8")
    copy = text.index('cp "$work/app.yaml" "$work/worker.yaml"')
    first_mount = text.index('mount="/secrets/')
    assert text.index('worker_extra="$extra"') < first_mount
    assert copy < first_mount
    assert text.index("DEPLOYMENT_ENVIRONMENT: ") < copy


def _run_secret_loop(tmp_path: Path) -> tuple[str, str]:
    """Runs the worker/API secret block of deploy.sh with every secret present (stubbed)."""
    text = DEPLOY.read_text(encoding="utf-8")
    start = text.index('worker_extra="$extra"')
    end = text.index("done", text.index("for pair in PROVIDER_CONFIG_FILE", start)) + len("done")
    script = (
        "secret_exists() { true; }\nenv_name=dev\nextra=\nwork=$1\n"
        + text[start:end]
        + '\nprintf "%s\\n%s\\n" "$worker_extra" "$extra"\n'
    )
    (tmp_path / "app.yaml").write_text("DEPLOYMENT_ENVIRONMENT: dev\n", encoding="utf-8")
    out = subprocess.run(  # noqa: S603 - a fixed script, no user input
        ["bash", "-c", script, "deploy", str(tmp_path)],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    return out[0], out[1]


def test_the_worker_gets_each_content_secret_as_an_environment_variable(tmp_path: Path) -> None:
    """The worker reads its content from <NAME>_CONTENT (app/config.py), never from a mount."""
    worker, api = _run_secret_loop(tmp_path)

    names = ["PROVIDER_CONFIG", "PRICE_TABLE", "PROFILE_DEFINITION", "PROMPT_SET"]
    names += ["COUNTRY_TABLE", "PDF_DISCLAIMER"]
    for name in names:
        secret = name.lower().replace("_", "-")
        assert f",{name}_CONTENT=iscan-dev-{secret}:latest" in worker
    assert "/secrets/" not in worker
    assert "/secrets/provider-config/content.json=iscan-dev-provider-config:latest" in api
    assert "_CONTENT=" not in api
    assert "PROVIDER_CONFIG_FILE" not in (tmp_path / "worker.yaml").read_text(encoding="utf-8")
