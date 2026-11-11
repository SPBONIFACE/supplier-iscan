"""Cloud Run worker pools refuse secret volume mounts ("Secrets volume mount is not supported for
Worker Pools yet"), so the deploy must never pass a content-file mount to the worker pool."""

import re
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
