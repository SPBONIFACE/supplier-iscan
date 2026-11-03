"""Fetch the name-detection model for redaction (#19): pinned revision, sha256-checked, no secret.

Run at image build and by `make install`; the application itself never downloads anything (it runs
with HF_HUB_OFFLINE=1 and TRANSFORMERS_OFFLINE=1). Standard library only.

    python scripts/fetch_model.py [DIRECTORY]

DIRECTORY defaults to $REDACTION_MODEL_DIR, then ~/.cache/supplier-iscan/gliner-multi-pii-<rev>
(outside the repository). Files already present with the right hash are kept, so a second run is
instant and works offline. A file with a wrong hash is an error: nothing is loaded from it.

Layout written (the loader in app/redaction/detector.py reads exactly this):
    gliner_config.json   upstream file, with "model_name" pointing to ./backbone (absolute path)
    pytorch_model.bin    the checkpoint (a pickle: loaded with torch.load(weights_only=True) only)
    backbone/            config and tokenizer files of the encoder (no weights)
"""

import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

MODEL_REPO = "urchade/gliner_multi_pii-v1"  # Apache-2.0
MODEL_REVISION = "1fcf13e85f4eef5394e1fcd406cf2ca9ea82351d"
BACKBONE_REPO = "microsoft/mdeberta-v3-base"  # MIT, config and tokenizer files only
BACKBONE_REVISION = "a0484667b22365f84929a935b5e50a51f71f159d"

# (repository, revision, file name in the repository, destination relative to the directory, sha256)
FILES = (
    (
        MODEL_REPO,
        MODEL_REVISION,
        "pytorch_model.bin",
        "pytorch_model.bin",
        "3003753fba99e40645cf088c7367a2c6211fc174897dc64f1f9c147c29d18d2d",
    ),
    (
        MODEL_REPO,
        MODEL_REVISION,
        "gliner_config.json",
        "gliner_config.upstream.json",
        "2088bee85f50849dea2ab4cf411ab5cf3aaaf7c8a45c23412035978b2bc02801",
    ),
    (
        BACKBONE_REPO,
        BACKBONE_REVISION,
        "config.json",
        "backbone/config.json",
        "bcffcd343dc5efa5ef2d5a58d2b405eed108f01cc45b48d0a907b333ec41801f",
    ),
    (
        BACKBONE_REPO,
        BACKBONE_REVISION,
        "spm.model",
        "backbone/spm.model",
        "13c8d666d62a7bc4ac8f040aab68e942c861f93303156cc28f5c7e885d86d6e3",
    ),
    (
        BACKBONE_REPO,
        BACKBONE_REVISION,
        "tokenizer_config.json",
        "backbone/tokenizer_config.json",
        "3f3978e0c036f2c2588cac34a6047cbb0af0b0dc1814254e291028529805496d",
    ),
)


def default_directory() -> Path:
    configured = os.environ.get("REDACTION_MODEL_DIR", "").strip()
    if configured:
        return Path(configured)
    return Path.home() / ".cache" / "supplier-iscan" / f"gliner-multi-pii-{MODEL_REVISION[:8]}"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(directory: Path) -> None:
    directory = directory.resolve()
    for repo, revision, name, destination, expected in FILES:
        target = directory / destination
        if target.is_file() and sha256_of(target) == expected:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".part")
        url = f"https://huggingface.co/{repo}/resolve/{revision}/{name}"
        print(f"downloading {repo}@{revision[:8]} {name}", file=sys.stderr)
        with urllib.request.urlopen(url, timeout=120) as response, partial.open("wb") as out:  # noqa: S310
            for block in iter(lambda: response.read(1 << 20), b""):
                out.write(block)
        if sha256_of(partial) != expected:
            partial.unlink()
            raise SystemExit(f"sha256 mismatch for {repo} {name}: file refused")
        partial.replace(target)
    config = json.loads((directory / "gliner_config.upstream.json").read_text(encoding="utf-8"))
    config["model_name"] = str(directory / "backbone")
    (directory / "gliner_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(f"model ready in {directory}", file=sys.stderr)


if __name__ == "__main__":
    fetch(Path(sys.argv[1]) if len(sys.argv) > 1 else default_directory())
