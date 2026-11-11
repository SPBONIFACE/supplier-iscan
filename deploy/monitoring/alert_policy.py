"""The failure-rate alert policy as code (#53). Standard library only.

    python3 deploy/monitoring/alert_policy.py render ENV   print the policy JSON (no cloud call)
    python3 deploy/monitoring/alert_policy.py apply ENV    create or update it (GCP_PROJECT_ID set)

The values (threshold, window, minimum finished runs, duration, auto-close, channels) are read from
deploy/monitoring/failure-rate.ENV.json. `apply` is idempotent: the policy is found by its display
name and updated in place, so running it twice leaves one policy. It fails when a channel named in
the file does not exist (the owner creates the two channels, runbook) or when two policies share the
display name. Needs roles/monitoring.alertPolicyEditor and
roles/monitoring.notificationChannelViewer.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
METRIC = "iscan_runs_finished_total"
SELECTOR = re.compile(r'([a-z_]+(=|!=|=~|!~)"[A-Za-z0-9_.:*|^$-]*"(,|$))*')

Runner = Callable[[Sequence[str]], str]


def load(environment: str, directory: Path = HERE) -> dict[str, Any]:
    if not re.fullmatch(r"[a-z]+", environment):
        raise SystemExit("ENV must be a lower-case name such as dev")
    path = directory / f"failure-rate.{environment}.json"
    if not path.is_file():
        raise SystemExit(f"No alert configuration for {environment}: {path.name}")
    config: dict[str, Any] = json.loads(path.read_text())
    if not 0 < float(config["threshold"]) < 1:
        raise SystemExit("threshold must be a rate between 0 and 1")
    for key in ("window_minutes", "min_finished_runs", "duration_minutes", "auto_close_minutes"):
        if not isinstance(config[key], int) or config[key] < 1:
            raise SystemExit(f"{key} must be a whole number above 0")
    if not SELECTOR.fullmatch(config.get("label_selector", "")):
        raise SystemExit("label_selector must be a list of PromQL label matchers")
    return config


def query(config: dict[str, Any]) -> str:
    """Failed / finished runs over the window, above the threshold, only when enough runs finished.
    The README's failure rate (Observability), with the minimum run count joined by `and on()`."""
    selector = config.get("label_selector", "")
    window = f"{config['window_minutes']}m"
    failed = ",".join(filter(None, ['iscan_status="failed"', selector]))
    finished = f"sum(increase({METRIC}{{{selector}}}[{window}]))"
    rate = f"sum(increase({METRIC}{{{failed}}}[{window}])) / {finished}"
    return (
        f"(({rate}) > {config['threshold']}) and on() ({finished} >= {config['min_finished_runs']})"
    )


def policy(config: dict[str, Any], channels: Sequence[str]) -> dict[str, Any]:
    """The AlertPolicy resource (Cloud Monitoring API v3). Its documentation holds the runbook link
    and the rule only: no personal data, no supplier content."""
    return {
        "displayName": config["display_name"],
        "documentation": {
            "mimeType": "text/markdown",
            "subject": f"[iscan {config['environment']}] profile-run failure rate above "
            f"{config['threshold']}",
            "content": (
                f"More than {config['threshold']} of the profile runs finished in the last "
                f"{config['window_minutes']} minutes failed (at least "
                f"{config['min_finished_runs']} runs finished), for {config['duration_minutes']} "
                f"minutes. The on-call agent is woken through the alert relay and opens an "
                f"`incident` issue. Runbook: {config['runbook_url']}"
            ),
        },
        "userLabels": {"app": "iscan", "env": config["environment"]},
        "combiner": "OR",
        "severity": "ERROR",
        "conditions": [
            {
                "displayName": "Failure rate of finished profile runs",
                "conditionPrometheusQueryLanguage": {
                    "query": query(config),
                    "duration": f"{config['duration_minutes'] * 60}s",
                    "evaluationInterval": f"{config['evaluation_interval_seconds']}s",
                },
            }
        ],
        # The incident closes by itself once the condition is no longer met (the rate is back
        # below the threshold, or too few runs finished); autoClose also ends it when data stops.
        "alertStrategy": {
            "autoClose": f"{config['auto_close_minutes'] * 60}s",
            "notificationPrompts": ["OPENED", "CLOSED"],
        },
        "notificationChannels": list(channels),
    }


def gcloud_runner(project: str) -> Runner:
    def run(args: Sequence[str]) -> str:
        command = ["gcloud", "--project", project, "--quiet", *args]
        return subprocess.run(command, check=True, capture_output=True, text=True).stdout  # noqa: S603

    return run


def names(run: Runner, kind: str, display_name: str) -> list[str]:
    output = run(
        [
            "beta",
            "monitoring",
            kind,
            "list",
            f'--filter=displayName="{display_name}"',
            "--format=value(name)",
        ]
    )
    return [line.strip() for line in output.splitlines() if line.strip()]


def apply(config: dict[str, Any], run: Runner) -> str:
    """Create the policy, or update the one with the same display name. Returns what was done."""
    channels: list[str] = []
    for channel in config["channels"]:
        found = names(run, "channels", channel)
        if len(found) != 1:
            raise SystemExit(
                f"Notification channel {channel!r}: expected one, found {len(found)} (runbook)"
            )
        channels.extend(found)
    existing = names(run, "policies", config["display_name"])
    if len(existing) > 1:
        raise SystemExit(f"{len(existing)} policies are named {config['display_name']!r}: keep one")
    with tempfile.TemporaryDirectory() as work:
        path = Path(work) / "policy.json"
        path.write_text(json.dumps(policy(config, channels)))
        if existing:
            run(
                [
                    "beta",
                    "monitoring",
                    "policies",
                    "update",
                    existing[0],
                    f"--policy-from-file={path}",
                ]
            )
            return f"updated {existing[0]}"
        run(["beta", "monitoring", "policies", "create", f"--policy-from-file={path}"])
        return "created"


def main(argv: Sequence[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("render", "apply"):
        print("usage: alert_policy.py render|apply ENV", file=sys.stderr)
        return 2
    config = load(argv[2])
    if argv[1] == "render":
        print(json.dumps(policy(config, config["channels"]), indent=2))
        return 0
    project = os.environ.get("GCP_PROJECT_ID", "").strip()
    if not project:
        print("Missing setting: GCP_PROJECT_ID", file=sys.stderr)
        return 2
    print(f"Alert policy {config['display_name']!r}: {apply(config, gcloud_runner(project))}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
