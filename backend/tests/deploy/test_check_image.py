"""The image check of the pipeline (deploy/check_image.py): what it refuses and what it passes."""

import importlib.util
import io
import json
import sys
import tarfile
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "deploy" / "check_image.py"

# Built at run time so that this file never holds a credential-shaped literal of its own.
PRIVATE_KEY = "-----BEGIN " + "RSA PRIVATE KEY-----\nabc\n"
AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"
GITHUB_TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_image", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_image"] = module
    spec.loader.exec_module(module)
    return module


def layer(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def image_archive(path: Path, layers: list[dict[str, str]]) -> str:
    names = [f"blobs/layer{index}/layer.tar" for index in range(len(layers))]
    with tarfile.open(path, "w") as archive:
        for name, files in zip(names, layers, strict=True):
            data = layer(files)
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        manifest = json.dumps([{"Layers": names}]).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest)
        archive.addfile(info, io.BytesIO(manifest))
    return str(path)


def check(checker: ModuleType, tmp_path: Path, *layers: dict[str, str]) -> tuple[int, str]:
    report = checker.Report()
    checker.scan_archive(report, image_archive(tmp_path / "image.tar", list(layers)))
    return (1 if report.findings else 0), "\n".join(report.findings)


def test_a_clean_image_passes(checker: ModuleType, tmp_path: Path) -> None:
    failed, findings = check(
        checker,
        tmp_path,
        {
            "app/main.py": "print('hello')\n",
            "app/config.py": "url = 'postgresql://u:password@db/x'\n",
        },
        {"usr/share/nginx/html/index.html": "<html></html>"},
    )

    assert (failed, findings) == (0, "")


@pytest.mark.parametrize(
    ("files", "rule"),
    [
        ({"app/.env": "A=1\n"}, "environment file"),
        ({"app/.env.production": "A=1\n"}, "environment file"),
        ({"app/_private/content/profile.json": "{}"}, "content of _private/"),
        ({"root/.ssh/id_ed25519": "x"}, "credential file name"),
        ({"app/keys/server.p12": "x"}, "private key or keystore file name"),
        ({"app/notes.txt": PRIVATE_KEY}, "private key block"),
        ({"app/a.txt": f"key={AWS_KEY}"}, "AWS access key id"),
        ({"usr/share/nginx/html/assets/app.js": f'token:"{GITHUB_TOKEN}"'}, "GitHub token"),
        (
            {"app/db.py": "u='postgresql://owner:Xk29sd0pQ@ep-cool-1.neon.tech/main'"},
            "connection URL",
        ),
        ({"app/sa.json": '{"type": "service_account"}'}, "Google service-account key"),
    ],
)
def test_a_forbidden_file_or_pattern_fails_and_the_finding_names_the_rule(
    checker: ModuleType, tmp_path: Path, files: dict[str, str], rule: str
) -> None:
    failed, findings = check(checker, tmp_path, files)

    assert failed and rule in findings


def test_a_finding_never_repeats_the_matched_secret(checker: ModuleType, tmp_path: Path) -> None:
    _, findings = check(checker, tmp_path, {"app/a.txt": f"{AWS_KEY} {GITHUB_TOKEN}"})

    assert AWS_KEY not in findings and GITHUB_TOKEN not in findings


def test_a_secret_in_an_earlier_layer_counts_although_a_later_layer_deletes_it(
    checker: ModuleType, tmp_path: Path
) -> None:
    failed, findings = check(checker, tmp_path, {"app/.env": "A=1\n"}, {"app/.wh..env": ""})

    assert failed and "environment file" in findings


def test_third_party_files_are_not_judged_by_name_or_content(
    checker: ModuleType, tmp_path: Path
) -> None:
    failed, _ = check(
        checker,
        tmp_path,
        {
            "opt/venv/lib/python3.13/site-packages/pkg/tests/server.key": PRIVATE_KEY,
            "usr/share/doc/pkg/example.txt": PRIVATE_KEY,
            "etc/ssl/certs/ca.pem": "-----BEGIN CERTIFICATE-----\n",
            "opt/venv/lib/python3.13/site-packages/numpy/testing/_private/utils.py": "x = 1\n",
            "root/.cache/uv/archive-v0/abc/pkg/tests/test_keys.py": PRIVATE_KEY,
        },
    )

    assert not failed


def test_the_directory_mode_applies_the_same_rules(checker: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / ".env").write_text("A=1\n")
    report = checker.Report()

    checker.scan_directory(report, str(tmp_path))

    assert any("environment file" in finding for finding in report.findings)


def test_an_image_over_the_size_limit_fails(
    checker: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = checker.Report()
    checker.scan_archive(
        report, image_archive(tmp_path / "i.tar", [{"app/big.txt": "x" * 3_000_000}])
    )

    assert checker.run(report, max_size_mb=1) == 1
    assert "larger than 1 MB" in capsys.readouterr().err
