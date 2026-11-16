"""The worker gets its content secrets as environment variables, never as file mounts: Cloud Run
worker pools refused secret volume mounts, and the worker job (#200) keeps the same form."""

import re
import subprocess
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[3] / "deploy" / "deploy.sh"


def _worker_deploy_command() -> str:
    text = DEPLOY.read_text(encoding="utf-8")
    match = re.search(r'run jobs deploy "\$worker_job" .*?(?:\n\s*#|\n\s*\n|\Z)', text, re.DOTALL)
    assert match, "no worker job deploy command in deploy.sh"
    return match.group(0)


def test_the_worker_job_gets_no_content_file_mounts() -> None:
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


def test_the_worker_is_a_job_in_drain_mode_with_the_cost_caps() -> None:
    command = _worker_deploy_command()
    assert '--args="-m,app.worker,--until-empty"' in command
    assert "--tasks 1 --max-retries 0 --task-timeout 3600" in command
    assert '--service-account "$runtime_sa"' in command
    assert '--container collector --image "$IMAGE_COLLECTOR"' in command
    # Non-container flags must come before the first --container.
    assert command.index("--task-timeout") < command.index("--container")


def test_the_deploy_never_runs_the_worker_and_grants_start_on_the_job_only() -> None:
    text = DEPLOY.read_text(encoding="utf-8")
    assert 'jobs execute "$worker_job"' not in text
    assert "worker-pools deploy" not in text
    grant = re.search(r"add-iam-policy-binding.*?roles/run\.invoker", text, re.DOTALL)
    assert grant and grant.group(0).startswith('add-iam-policy-binding "$worker_job"')
    assert "projects add-iam-policy-binding" not in text


def test_only_the_api_gets_the_worker_job_name() -> None:
    text = DEPLOY.read_text(encoding="utf-8")
    line = text.index("WORKER_JOB_NAME: ")
    assert text.index('cp "$work/app.yaml" "$work/worker.yaml"') < line
    assert '>> "$work/app.yaml"' in text[line : text.index("\n", line)]
    assert "jobs/$worker_job" in text[line : text.index("\n", line)]
