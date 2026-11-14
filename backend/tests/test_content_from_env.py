"""A content file given as its content (<NAME>_CONTENT), for the Cloud Run worker pool, which
cannot mount a secret as a file: it is written once to a private file and used as <NAME>_FILE."""

import json
import stat
from pathlib import Path

import pytest

from app.config import load_settings
from app.providers.catalogue import load_catalogue

CONTENT = json.dumps({"$comment": "test content", "items": []})


@pytest.fixture(autouse=True)
def _private_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))


def test_each_content_setting_becomes_a_private_file(tmp_path: Path) -> None:
    names = ["PROVIDER_CONFIG", "PRICE_TABLE", "PROFILE_DEFINITION", "PROMPT_SET"]
    names += ["COUNTRY_TABLE", "PDF_DISCLAIMER"]
    settings = load_settings({f"{name}_CONTENT": f"{CONTENT} " + name for name in names})

    paths = [
        settings.provider_config_file,
        settings.price_table_file,
        settings.profile_definition_file,
        settings.prompt_set_file,
        settings.country_table_file,
        settings.pdf_disclaimer_file,
    ]
    for name, path in zip(names, paths, strict=True):
        assert path is not None
        file = Path(path)
        assert file.read_text(encoding="utf-8") == f"{CONTENT} " + name
        assert stat.S_IMODE(file.stat().st_mode) == 0o600
        assert file.parent == tmp_path / "supplier-iscan-content"
    assert stat.S_IMODE((tmp_path / "supplier-iscan-content").stat().st_mode) == 0o700


def test_a_file_setting_wins_and_nothing_is_written(tmp_path: Path) -> None:
    settings = load_settings(
        {"PROVIDER_CONFIG_FILE": "/given/path.json", "PROVIDER_CONFIG_CONTENT": CONTENT}
    )

    assert settings.provider_config_file == "/given/path.json"
    assert not (tmp_path / "supplier-iscan-content").exists()


def test_no_setting_keeps_the_shipped_example() -> None:
    settings = load_settings({"PROVIDER_CONFIG_CONTENT": "  "})

    assert settings.provider_config_file is None


def test_loading_again_reuses_the_same_file() -> None:
    first = load_settings({"PROMPT_SET_CONTENT": CONTENT}).prompt_set_file
    second = load_settings({"PROMPT_SET_CONTENT": CONTENT}).prompt_set_file

    assert first == second


def test_the_worker_reads_an_enabled_provider_configuration_from_the_content(
    tmp_path: Path,
) -> None:
    """The dev failure: the worker fell back to the example, where every record is disabled."""
    example = Path(__file__).parents[1] / "app" / "providers" / "provider_configs.example.json"
    data = json.loads(example.read_text(encoding="utf-8"))
    for record in data["provider_configs"]:
        record["enabled"] = True
        record["verified_at"] = "2026-11-14T00:00:00Z"

    settings = load_settings({"PROVIDER_CONFIG_CONTENT": json.dumps(data)})
    assert settings.provider_config_file is not None
    catalogue = load_catalogue(Path(settings.provider_config_file))

    assert catalogue.by_id and all(config.approved for config in catalogue.by_id.values())
