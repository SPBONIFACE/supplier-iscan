"""Fixtures of the redaction tests.

Fast tests use a fake detector (`support.FakeDetector`). Tests marked `model` use the real GLiNER
model, which `make fetch-model` puts outside the repository; they are not run by `make test`
(`-m "not model"`) but by `make test-model` and by CI. Without the model they are skipped locally
and fail in CI.
"""

import os
from pathlib import Path

import pytest

from app.redaction import Redactor, get_redactor
from app.redaction.detector import model_directory


@pytest.fixture(scope="session")
def real_redactor() -> Redactor:
    if not (Path(model_directory()) / "pytorch_model.bin").is_file():
        if os.environ.get("CI"):
            pytest.fail("the redaction model is missing in CI: run `make fetch-model`")
        pytest.skip("the redaction model is not fetched: run `make fetch-model`")
    redactor = get_redactor()
    redactor.load()
    return redactor
