#!/usr/bin/env python3
"""Check a built container image before it is pushed: no secret, no private file, and a size report.

    deploy/check_image.py IMAGE [--max-size-mb N]      IMAGE is a name known to Docker (docker save)
    deploy/check_image.py --archive FILE.tar           a `docker save` archive
    deploy/check_image.py --directory DIR              a plain directory (used by the tests)

It fails (exit 1) when any layer of the image holds:
  - an environment file (`.env`, `.env.*`),
  - a private key (by file name, or by a `-----BEGIN ... PRIVATE KEY-----` block),
  - anything under `_private/` (the owner's private repository),
  - a known credential file name (service-account key, `.netrc`, `.pgpass`, ...),
  - a credential pattern (cloud, LLM provider, GitHub tokens, a password inside a connection URL).
It also fails when the image is larger than --max-size-mb. It prints a size report either way.
A file deleted by a later layer still counts: it is still in the image. A finding names the path
and the rule, never the matched text, so a log never repeats a secret.

Standard library only; Python 3.9 or later.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import PurePosixPath

MAX_SCANNED_BYTES = 2_000_000
BINARY_SUFFIXES = {
    ".so", ".pyc", ".pyo", ".bin", ".safetensors", ".pt", ".pth", ".onnx", ".npy", ".npz",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2", ".ttf", ".otf",
    ".gz", ".xz", ".zip", ".whl", ".a", ".o", ".pdf", ".mo", ".db",
}  # fmt: skip
# Content is not read under these prefixes (system and third-party files, not ours); file NAMES are
# checked everywhere. `usr/share/nginx/` (the built frontend) is read though under usr/share.
CONTENT_SKIPPED = (
    "opt/model/",
    "root/.cache/uv/",
    "usr/lib/",
    "usr/share/",
    "usr/local/lib/",
    "lib/",
    "var/lib/dpkg/",
    "var/lib/apt/",
    "var/cache/",
    "etc/ssl/",
    "etc/ca-certificates",
)
CONTENT_READ_ANYWAY = ("usr/share/nginx/",)
VENV_LIBRARIES = re.compile(r"^opt/venv/lib/[^/]+/site-packages/")

CREDENTIAL_FILE_NAMES = {
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".netrc", ".pgpass", ".git-credentials",
    ".npmrc", ".pypirc", "credentials.json", "service-account.json", "service_account.json",
    "application_default_credentials.json", "secrets.json", "secret.json", "token.json",
}  # fmt: skip
PRIVATE_KEY_SUFFIXES = (".p12", ".pfx", ".jks", ".keystore", ".key")
# Third-party and system files: credential-like names are not judged there (test data of packages).
LIBRARY_PREFIXES = (
    "opt/venv/lib/",
    "opt/model/",
    "root/.cache/uv/",
    "usr/lib/",
    "usr/share/",
    "usr/local/lib/",
    "lib/",
)
PRIVATE_DIRECTORIES = {"_private", "supplier-iscan-private"}

PLACEHOLDER_HOSTS = re.compile(
    r"^(localhost|127\.0\.0\.1|0\.0\.0\.0|db|host|hostname|example\.[a-z]+|.*\.example|.*\.test)$"
)
PLACEHOLDER_PASSWORDS = re.compile(
    r"^(password|passwd|pass|secret|xxx+|\*+|changeme|\$\{?\w+\}?)$", re.I
)
URL_CREDENTIALS = re.compile(
    rb"[a-z][a-z0-9+.-]{1,20}://([^/\s:@'\"]+):([^/\s@'\"]{4,})@([^/\s:'\"?#]+)"
)

# (rule name, pattern). The names appear in findings; the matched text never does.
CONTENT_RULES: list[tuple[str, re.Pattern[bytes]]] = [
    ("private key block", re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("Google service-account key", re.compile(rb'"type"\s*:\s*"service_account"')),
    ("Google API key", re.compile(rb"AIza[0-9A-Za-z_\-]{35}")),
    ("AWS access key id", re.compile(rb"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("Anthropic key", re.compile(rb"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("OpenAI key", re.compile(rb"\bsk-(proj-)?[A-Za-z0-9_\-]{32,}")),
    ("Perplexity key", re.compile(rb"\bpplx-[A-Za-z0-9]{32,}")),
    ("GitHub token", re.compile(rb"\b(gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})")),
    ("Slack token", re.compile(rb"\bxox[baprs]-[A-Za-z0-9\-]{10,}")),
]


@dataclass
class Report:
    findings: list[str] = field(default_factory=list)
    total_bytes: int = 0
    files: int = 0
    largest: list[tuple[int, str]] = field(default_factory=list)
    layers: list[tuple[str, int]] = field(default_factory=list)

    def add_file(self, path: str, size: int) -> None:
        self.files += 1
        self.total_bytes += size
        self.largest.append((size, path))
        if len(self.largest) > 200:
            self.largest = sorted(self.largest, reverse=True)[:20]


def normalise(path: str) -> str:
    return str(PurePosixPath(path.lstrip("./"))) if path.strip("./") else ""


def check_name(path: str) -> list[str]:
    """Rules that apply to a file name or its directory, wherever the file is."""
    parts = PurePosixPath(path).parts
    name = parts[-1] if parts else ""
    found: list[str] = []
    if name == ".env" or name.startswith(".env."):
        found.append("environment file")
    # Third-party packages have directories called _private (numpy.testing._private): not ours.
    if PRIVATE_DIRECTORIES & set(parts) and not path.startswith(LIBRARY_PREFIXES):
        found.append("content of _private/")
    if not path.startswith(LIBRARY_PREFIXES):
        if name in CREDENTIAL_FILE_NAMES:
            found.append("credential file name")
        if name.endswith(PRIVATE_KEY_SUFFIXES):
            found.append("private key or keystore file name")
    return found


def should_read(path: str, size: int) -> bool:
    if size == 0 or size > MAX_SCANNED_BYTES:
        return False
    if PurePosixPath(path).suffix.lower() in BINARY_SUFFIXES:
        return False
    if VENV_LIBRARIES.match(path):
        return False
    if path.startswith(CONTENT_READ_ANYWAY):
        return True
    return not path.startswith(CONTENT_SKIPPED)


def check_content(data: bytes) -> list[str]:
    found = [name for name, pattern in CONTENT_RULES if pattern.search(data)]
    for match in URL_CREDENTIALS.finditer(data):
        host = match.group(3).decode("utf-8", "replace").lower()
        password = match.group(2).decode("utf-8", "replace")
        if not PLACEHOLDER_HOSTS.match(host) and not PLACEHOLDER_PASSWORDS.match(password):
            found.append("password inside a connection URL")
            break
    return found


def scan_entry(report: Report, layer: str, path: str, size: int, read: Callable[[], bytes]) -> None:
    path = normalise(path)
    if not path:
        return
    report.add_file(path, size)
    for rule in check_name(path):
        report.findings.append(f"{layer}: /{path}: {rule}")
    if should_read(path, size):
        for rule in check_content(read()):
            report.findings.append(f"{layer}: /{path}: {rule}")


def scan_tar_stream(report: Report, label: str, tar: tarfile.TarFile) -> int:
    layer_bytes = 0
    for member in tar:
        if not member.isfile():
            # A whiteout (.wh.name) is a deletion marker; its name is still checked below.
            if member.name:
                for rule in check_name(normalise(member.name)):
                    report.findings.append(f"{label}: /{normalise(member.name)}: {rule}")
            continue
        layer_bytes += member.size
        handle = tar.extractfile(member)
        scan_entry(
            report, label, member.name, member.size, (lambda h=handle: h.read() if h else b"")
        )
    return layer_bytes


def scan_archive(report: Report, archive_path: str) -> None:
    with tarfile.open(archive_path, "r:") as archive:
        manifest = archive.extractfile("manifest.json")
        if manifest is None:
            raise SystemExit("not a docker save archive: manifest.json is missing")
        entries = json.load(manifest)
        for entry in entries:
            for layer_name in entry["Layers"]:
                layer_file = archive.extractfile(layer_name)
                if layer_file is None:
                    raise SystemExit(f"layer {layer_name} is missing from the archive")
                label = "layer " + layer_name.split("/")[-1][:12]
                with tarfile.open(fileobj=layer_file, mode="r|*") as layer:
                    report.layers.append((label, scan_tar_stream(report, label, layer)))


def scan_directory(report: Report, root: str) -> None:
    from pathlib import Path

    base = Path(root)
    total = 0
    for path in sorted(base.rglob("*")):
        relative = path.relative_to(base).as_posix()
        if path.is_file() and not path.is_symlink():
            size = path.stat().st_size
            total += size
            scan_entry(report, "directory", relative, size, path.read_bytes)
        elif path.name:
            for rule in check_name(relative):
                report.findings.append(f"directory: /{relative}: {rule}")
    report.layers.append(("directory", total))


def format_report(report: Report, max_size_mb: int | None) -> str:
    megabytes = report.total_bytes / 1_000_000
    lines = [f"Image content: {report.files} files, {megabytes:,.0f} MB uncompressed"]
    for label, size in report.layers:
        lines.append(f"  {label}: {size / 1_000_000:,.1f} MB")
    lines.append("Largest files:")
    for size, path in sorted(report.largest, reverse=True)[:8]:
        lines.append(f"  {size / 1_000_000:,.1f} MB  /{path}")
    if max_size_mb is not None:
        lines.append(f"Size limit: {max_size_mb} MB")
    return "\n".join(lines)


def run(report: Report, max_size_mb: int | None) -> int:
    print(format_report(report, max_size_mb))
    failed = False
    if max_size_mb is not None and report.total_bytes > max_size_mb * 1_000_000:
        print(f"FAIL: the image is larger than {max_size_mb} MB", file=sys.stderr)
        failed = True
    for finding in report.findings:
        print(f"FAIL: {finding}", file=sys.stderr)
        failed = True
    print("Image check: " + ("FAILED" if failed else "passed"))
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("image", nargs="?", help="image name known to Docker")
    parser.add_argument("--archive", help="a docker save archive")
    parser.add_argument("--directory", help="a plain directory")
    parser.add_argument("--max-size-mb", type=int, default=None)
    args = parser.parse_args(argv)
    if sum(bool(x) for x in (args.image, args.archive, args.directory)) != 1:
        parser.error("give exactly one of IMAGE, --archive, --directory")
    report = Report()
    if args.directory:
        scan_directory(report, args.directory)
    elif args.archive:
        scan_archive(report, args.archive)
    else:
        with tempfile.TemporaryDirectory() as workspace:
            archive_path = f"{workspace}/image.tar"
            # Fixed command; the image name is a single argument, never a shell string.
            subprocess.run(  # noqa: S603
                ["docker", "save", "--output", archive_path, args.image],  # noqa: S607
                check=True,
            )
            scan_archive(report, archive_path)
    return run(report, args.max_size_mb)


if __name__ == "__main__":
    sys.exit(main())
