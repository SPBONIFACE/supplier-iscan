"""The alert drill switch FAULT_INJECTION_FAIL_RUNS (#53): dev only, never on in prod."""

import os
import re
import subprocess
import uuid
from pathlib import Path

import pytest

from app.config import ConfigurationError, load_settings
from app.runs.stages import StageContext, SyntheticFaultInjected, classify, collection_stage
from tests.deploy.support import ROOT

ENV_DIR = ROOT / "deploy" / "env"


def test_switch_is_off_by_default() -> None:
    assert load_settings({}).fault_injection_fail_runs is False
    assert load_settings({"DEPLOYMENT_ENVIRONMENT": "dev"}).fault_injection_fail_runs is False


def test_switch_is_accepted_in_dev() -> None:
    settings = load_settings({"DEPLOYMENT_ENVIRONMENT": "dev", "FAULT_INJECTION_FAIL_RUNS": "true"})
    assert settings.fault_injection_fail_runs is True


@pytest.mark.parametrize("environment", ["prod", "", "Dev", "production"])
def test_switch_stops_startup_outside_dev(environment: str) -> None:
    with pytest.raises(ConfigurationError, match="FAULT_INJECTION_FAIL_RUNS"):
        load_settings({"DEPLOYMENT_ENVIRONMENT": environment, "FAULT_INJECTION_FAIL_RUNS": "true"})


def test_switch_accepts_only_true_or_false() -> None:
    with pytest.raises(ConfigurationError, match="true or false"):
        load_settings({"DEPLOYMENT_ENVIRONMENT": "dev", "FAULT_INJECTION_FAIL_RUNS": "1"})


def test_no_prod_configuration_file_sets_the_switch() -> None:
    prod_files = sorted(ENV_DIR.glob("prod*"))
    assert prod_files, "deploy/env/prod.* not found"
    for path in prod_files:
        assert "FAULT_INJECTION_FAIL_RUNS" not in path.read_text(), path.name


def test_dev_file_keeps_the_switch_off() -> None:
    values = re.findall(
        r'^\s*FAULT_INJECTION_FAIL_RUNS\s*:\s*"?([^"\s#]*)',
        (ENV_DIR / "dev.yaml").read_text(),
        re.M,
    )
    assert values in ([], ["false"])


def test_collection_fails_with_the_named_synthetic_error_when_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEPLOYMENT_ENVIRONMENT", "dev")
    monkeypatch.setenv("FAULT_INJECTION_FAIL_RUNS", "true")
    context = StageContext(uuid.uuid4(), uuid.uuid4(), "collection", None, None, lambda: None)  # type: ignore[arg-type]

    with pytest.raises(SyntheticFaultInjected) as raised:
        collection_stage(context)
    # Not a dependency failure: the run ends `failed` (counted in the failure rate), not paused.
    assert classify(raised.value) is None


def run_deploy(
    env_name: str, extra: dict[str, str], tmp_path: Path
) -> subprocess.CompletedProcess[str]:
    """deploy.sh with a gcloud that only records that it was called."""
    marker = tmp_path / "gcloud-called"
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "gcloud").write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n")
    (fake / "gcloud").chmod(0o755)
    env = {
        "PATH": f"{fake}:{os.environ['PATH']}",
        "GCP_PROJECT_ID": "test-project",
        "GCP_REGION": "europe-west3",
        **extra,
    }
    return subprocess.run(  # noqa: S603
        ["bash", str(ROOT / "deploy" / "deploy.sh"), env_name, "deploy"],  # noqa: S607
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("value", ["true", "TRUE", " yes ", "1"])
def test_deploy_refuses_prod_with_the_switch_before_any_cloud_call(
    value: str, tmp_path: Path
) -> None:
    result = run_deploy("prod", {"FAULT_INJECTION_FAIL_RUNS": value}, tmp_path)

    assert result.returncode == 2
    assert "dev only" in result.stderr
    assert not (tmp_path / "gcloud-called").exists()


def test_deploy_prod_without_the_switch_is_not_refused_by_it(tmp_path: Path) -> None:
    result = run_deploy("prod", {"FAULT_INJECTION_FAIL_RUNS": "false"}, tmp_path)

    assert "dev only" not in result.stderr  # it stops later, on the missing image settings


@pytest.mark.parametrize(
    "line", ['FAULT_INJECTION_FAIL_RUNS: "true"', "FAULT_INJECTION_FAIL_RUNS: yes"]
)
def test_deploy_refuses_prod_when_its_settings_file_sets_the_switch(
    line: str, tmp_path: Path
) -> None:
    copy = tmp_path / "deploy"
    (copy / "env").mkdir(parents=True)
    (copy / "deploy.sh").write_text((ROOT / "deploy" / "deploy.sh").read_text())
    for path in ENV_DIR.iterdir():
        (copy / "env" / path.name).write_text(path.read_text())
    with (copy / "env" / "prod.yaml").open("a") as prod:
        prod.write(line + "\n")
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "gcloud").write_text("#!/bin/sh\nexit 1\n")
    (fake / "gcloud").chmod(0o755)

    result = subprocess.run(  # noqa: S603
        ["bash", str(copy / "deploy.sh"), "prod", "deploy"],  # noqa: S607
        env={"PATH": f"{fake}:{os.environ['PATH']}", "GCP_PROJECT_ID": "p", "GCP_REGION": "r"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "dev only" in result.stderr
