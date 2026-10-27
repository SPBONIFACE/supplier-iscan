"""Criterion 6 of #15: no module outside the HTTP client module opens an outgoing HTTP connection.

Every Python module of the application (`backend/app/`, and the worker when it exists) is parsed;
importing a networking library, or loading one dynamically, anywhere outside `app/http_client/`
fails this test. Fetches to supplier sites go through `app.http_client.GuardedClient`.

Database drivers and the official LLM SDKs (which contact only their configured provider) are not
networking libraries in this sense and are not listed.
"""

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
REPOSITORY = BACKEND.parent
SCANNED_ROOTS = [BACKEND / "app", BACKEND / "worker", REPOSITORY / "worker"]
HTTP_CLIENT_MODULE = BACKEND / "app" / "http_client"

# Modules that open sockets or HTTP connections.
NETWORK_MODULES = frozenset(
    {
        "aiohttp",
        "ftplib",
        "http.client",
        "httpcore",
        "httpcore2",
        "httplib2",
        "httpx",
        "httpx2",
        "pycurl",
        "requests",
        "socket",
        "tornado.httpclient",
        "treq",
        "urllib.request",
        "urllib3",
        "websocket",
        "websockets",
    }
)
# Calls that open a connection from an otherwise allowed module.
NETWORK_ATTRIBUTES = frozenset(
    {
        ("asyncio", "open_connection"),
        ("asyncio", "create_connection"),
        ("urllib", "request"),
        ("http", "client"),
    }
)

# A module outside app/http_client that must open connections itself (to a host that is not a
# supplier site) is listed here with its reason, and reviewed like any security change.
ALLOWED_MODULES: dict[str, str] = {}


def _is_network_module(name: str) -> bool:
    return any(name == module or name.startswith(module + ".") for module in NETWORK_MODULES)


def find_network_access(source: str) -> list[str]:
    """Return a description of every networking import or dynamic load in `source`."""
    findings: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            findings += [
                f"line {node.lineno}: import {alias.name}"
                for alias in node.names
                if _is_network_module(alias.name)
            ]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]
            if any(_is_network_module(name) for name in names):
                findings.append(f"line {node.lineno}: from {node.module} import ...")
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if (node.value.id, node.attr) in NETWORK_ATTRIBUTES:
                findings.append(f"line {node.lineno}: {node.value.id}.{node.attr}")
        elif isinstance(node, ast.Call):
            for argument in node.args[:1]:
                if (
                    isinstance(argument, ast.Constant)
                    and isinstance(argument.value, str)
                    and _is_network_module(argument.value)
                    and _is_dynamic_import(node.func)
                ):
                    findings.append(f"line {node.lineno}: dynamic import of {argument.value}")
    return findings


def _is_dynamic_import(function: ast.expr) -> bool:
    if isinstance(function, ast.Name):
        return function.id in {"__import__", "import_module"}
    return isinstance(function, ast.Attribute) and function.attr == "import_module"


def _application_modules() -> list[Path]:
    modules: list[Path] = []
    for root in SCANNED_ROOTS:
        if root.is_dir():
            modules += [
                path
                for path in sorted(root.rglob("*.py"))
                if HTTP_CLIENT_MODULE not in path.parents and ".venv" not in path.parts
            ]
    return modules


def test_the_scan_covers_the_application() -> None:
    modules = _application_modules()

    assert BACKEND / "app" / "main.py" in modules
    assert not any(HTTP_CLIENT_MODULE in path.parents for path in modules)


def test_no_module_outside_the_http_client_opens_outgoing_connections() -> None:
    violations = {
        str(path.relative_to(REPOSITORY)): findings
        for path in _application_modules()
        if str(path.relative_to(REPOSITORY)) not in ALLOWED_MODULES
        and (findings := find_network_access(path.read_text(encoding="utf-8")))
    }

    assert violations == {}, (
        "Outgoing connections must go through app.http_client.GuardedClient (URL guard, #15): "
        f"{violations}"
    )


def test_the_http_client_module_itself_is_where_connections_are_made() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(HTTP_CLIENT_MODULE.rglob("*.py"))
    )

    assert find_network_access(sources)


@pytest.mark.parametrize(
    "source",
    [
        "import httpx2",
        "import httpx as client",
        "from httpx2 import Client",
        "from httpcore2._backends.sync import SyncBackend",
        "import requests",
        "import urllib.request",
        "from urllib.request import urlopen",
        "from urllib import request",
        "import http.client",
        "from http import client",
        "import socket",
        "from socket import create_connection",
        "import urllib3",
        "import aiohttp",
        "import urllib\nurllib.request.urlopen('https://example.com')",
        "import asyncio\nasyncio.open_connection('example.com', 80)",
        "__import__('httpx2')",
        "import importlib\nimportlib.import_module('requests')",
        "def f():\n    import httpx2\n    return httpx2",
    ],
)
def test_the_scan_detects_each_way_of_opening_a_connection(source: str) -> None:
    assert find_network_access(source)


@pytest.mark.parametrize(
    "source",
    [
        "import json",
        "from app.http_client import GuardedClient",
        "import psycopg",
        "from urllib.parse import urljoin",
        "import http\nhttp.HTTPStatus.OK",
        "import ipaddress",
    ],
)
def test_the_scan_allows_modules_that_open_no_connection(source: str) -> None:
    assert find_network_access(source) == []
