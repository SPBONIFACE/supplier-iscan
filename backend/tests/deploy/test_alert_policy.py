"""The failure-rate alert policy as code (#53): values from the file, idempotent apply.
No cloud call: gcloud is replaced by a small in-memory fake."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from tests.deploy.support import load_script

policy_script = load_script("deploy/monitoring/alert_policy.py", "alert_policy")


class FakeGcloud:
    """Policies and channels in memory, answering the four commands the script uses."""

    def __init__(
        self, channels: Sequence[str] = ("iscan-dev-email", "iscan-dev-alert-relay")
    ) -> None:
        self.channels = {
            name: f"projects/p/notificationChannels/{i}" for i, name in enumerate(channels)
        }
        self.policies: dict[str, dict[str, Any]] = {}
        self.calls: list[list[str]] = []

    def __call__(self, args: Sequence[str]) -> str:
        args = list(args)
        self.calls.append(args)
        assert args[:2] == ["beta", "monitoring"]
        kind, verb = args[2], args[3]
        if verb == "list":
            wanted = args[4].split('"')[1]
            table = (
                self.channels
                if kind == "channels"
                else {body["displayName"]: name for name, body in self.policies.items()}
            )
            return "\n".join(name for display, name in table.items() if display == wanted)
        body = json.loads(Path(args[-1].split("=", 1)[1]).read_text())
        if verb == "create":
            self.policies[f"projects/p/alertPolicies/{len(self.policies)}"] = body
        elif verb == "update":
            self.policies[args[4]] = body
        return ""


def config() -> dict[str, Any]:
    values: dict[str, Any] = policy_script.load("dev")
    return values


def test_dev_values_are_the_approved_ones_and_live_in_the_file() -> None:
    values = config()
    assert (values["threshold"], values["window_minutes"], values["min_finished_runs"]) == (
        0.5,
        15,
        3,
    )
    assert values["duration_minutes"] == 5


def test_query_is_the_failure_rate_gated_by_the_minimum_run_count() -> None:
    query = policy_script.query(config())

    assert query == (
        '((sum(increase(iscan_runs_finished_total{iscan_status="failed"}[15m])) / '
        "sum(increase(iscan_runs_finished_total{}[15m]))) > 0.5) "
        "and on() (sum(increase(iscan_runs_finished_total{}[15m])) >= 3)"
    )


def test_changed_values_change_the_policy() -> None:
    values = {**config(), "threshold": 0.3, "window_minutes": 30, "min_finished_runs": 5}
    values["duration_minutes"] = 10
    rendered = policy_script.policy(values, ["c1"])
    condition = rendered["conditions"][0]["conditionPrometheusQueryLanguage"]

    assert "[30m]" in condition["query"] and "> 0.3" in condition["query"]
    assert ">= 5" in condition["query"]
    assert condition["duration"] == "600s"


def test_policy_links_the_runbook_auto_closes_and_holds_no_personal_data() -> None:
    rendered = policy_script.policy(config(), ["a", "b"])

    assert "oncall-runbook.md" in rendered["documentation"]["content"]
    assert rendered["alertStrategy"]["autoClose"] == "1800s"
    assert rendered["notificationChannels"] == ["a", "b"]
    assert "@" not in json.dumps(rendered["documentation"])


def test_apply_twice_leaves_one_policy_with_both_channels() -> None:
    gcloud = FakeGcloud()

    assert policy_script.apply(config(), gcloud) == "created"
    assert policy_script.apply(config(), gcloud).startswith("updated")

    assert len(gcloud.policies) == 1
    (policy,) = gcloud.policies.values()
    assert policy["notificationChannels"] == list(gcloud.channels.values())


def test_apply_refuses_when_a_channel_is_missing() -> None:
    gcloud = FakeGcloud(channels=["iscan-dev-email"])

    with pytest.raises(SystemExit, match="iscan-dev-alert-relay"):
        policy_script.apply(config(), gcloud)
    assert gcloud.policies == {}


@pytest.mark.parametrize(
    "change",
    [
        {"threshold": 1.5},
        {"window_minutes": 0},
        {"min_finished_runs": "3"},
        {"label_selector": 'job="x"} or vector(1) #'},
    ],
)
def test_bad_values_are_refused(change: dict[str, Any], tmp_path: Path) -> None:
    (tmp_path / "failure-rate.dev.json").write_text(json.dumps({**config(), **change}))

    with pytest.raises(SystemExit):
        policy_script.load("dev", tmp_path)
