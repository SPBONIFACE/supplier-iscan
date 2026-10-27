"""Criterion 6 of #15: no module outside the HTTP client module opens an outgoing HTTP connection.

Every Python module of the application (`backend/app/`, and the worker when it exists) is parsed.
Outside `app/http_client/`, the test fails on:

- an import of a networking library (`import httpx2`, `from asyncio import open_connection`,
  `import xmlrpc.client`, ...), or a dynamic load of one (`__import__`, `import_module`);
- a name that is, or gives access to, a networking library or an unguarded transport, whatever it
  is imported from or reached through: `from app.http_client.url_guard import httpx2`,
  `url_guard.socket`, `loop.create_connection(...)`, `getattr(module, "httpx2")`;
- any use of the HTTP client package other than its public surface: only the names in
  `app/http_client/__init__.py`'s `__all__` may be imported, and its submodules (where the raw
  library and the inner transport live) may not be imported or reached at all.

Fetches to supplier sites go through `app.http_client.GuardedClient` and `check_website`. A static
scan cannot see code built at run time (`exec`, computed module names); review catches those.

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
HTTP_CLIENT_PACKAGE = "app.http_client"

# Modules that open sockets or network connections.
NETWORK_MODULES = frozenset(
    {
        "aiohttp",
        "asyncio.streams",
        "ftplib",
        "http.client",
        "httpcore",
        "httpcore2",
        "httplib2",
        "httpx",
        "httpx2",
        "imaplib",
        "multiprocessing.connection",
        "nntplib",
        "poplib",
        "pycurl",
        "requests",
        "smtplib",
        "socket",
        "telnetlib",
        "tornado.httpclient",
        "treq",
        "urllib.request",
        "urllib3",
        "websocket",
        "websockets",
        "xmlrpc.client",
    }
)
# Names bound to a networking library: refused as an imported name or as an attribute, whatever
# the module they come from (a re-export through another module is still the raw library).
NETWORK_NAMES = frozenset(
    {
        "aiohttp",
        "ftplib",
        "httpcore",
        "httpcore2",
        "httplib2",
        "httpx",
        "httpx2",
        "imaplib",
        "nntplib",
        "poplib",
        "pycurl",
        "requests",
        "smtplib",
        "socket",
        "telnetlib",
        "treq",
        "urllib3",
        "websocket",
        "websockets",
    }
)
# Functions and classes that open a connection, refused as imported names and as attributes on
# any object (`asyncio.open_connection`, `loop.create_connection`, `ssl.get_server_certificate`).
CONNECTION_NAMES = frozenset(
    {
        "ConnectionPool",
        "HTTPConnection",
        "HTTPSConnection",
        "HTTPTransport",
        "ServerProxy",
        "SyncBackend",
        "create_connection",
        "create_datagram_endpoint",
        "create_unix_connection",
        "get_server_certificate",
        "open_connection",
        "open_unix_connection",
        "sock_connect",
        "urlopen",
    }
)
# The HTTP client's own unguarded parts: its transports and their internals.
HTTP_CLIENT_INTERNAL_NAMES = frozenset(
    {
        "GuardedTransport",
        "default_inner_transport",
        "_DeadlineBackend",
        "_DeadlineHTTPTransport",
        "_DeadlineStream",
        "_inner",
        "_network_backend",
        "_pool",
    }
)

# A module outside app/http_client that must open connections itself (to a host that is not a
# supplier site) is listed here with its reason, and reviewed like any security change.
ALLOWED_MODULES: dict[str, str] = {}


def _public_surface() -> frozenset[str]:
    """The names in `__all__` of app/http_client/__init__.py, read without importing it."""
    tree = ast.parse((HTTP_CLIENT_MODULE / "__init__.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            return frozenset(ast.literal_eval(node.value))
    raise AssertionError("app/http_client/__init__.py must declare __all__")


PUBLIC_SURFACE = _public_surface()
HTTP_CLIENT_SUBMODULES = frozenset(
    path.stem for path in HTTP_CLIENT_MODULE.glob("*.py") if path.stem != "__init__"
) | frozenset(path.name for path in HTTP_CLIENT_MODULE.iterdir() if path.is_dir())


def _is_network_module(name: str) -> bool:
    return any(name == module or name.startswith(module + ".") for module in NETWORK_MODULES)


def _is_http_client_internal(name: str) -> bool:
    return name.startswith(HTTP_CLIENT_PACKAGE + ".")


def _is_forbidden_module(name: str) -> bool:
    return _is_network_module(name) or _is_http_client_internal(name)


def _is_forbidden_name(name: str) -> bool:
    return name in NETWORK_NAMES or name in CONNECTION_NAMES or name in HTTP_CLIENT_INTERNAL_NAMES


def _absolute_module(node: ast.ImportFrom, module: str | None) -> str | None:
    """The absolute module of `from ... import`, relative imports resolved against `module`."""
    if node.level == 0:
        return node.module
    if module is None:
        return None
    parts = module.split(".")[: -node.level]
    if node.module:
        parts.append(node.module)
    return ".".join(parts) or None


def _package_aliases(tree: ast.AST, module: str | None) -> frozenset[str]:
    """Local names bound to the `app.http_client` package (`import app.http_client as h`)."""
    aliases = {"http_client"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases |= {
                alias.asname
                for alias in node.names
                if alias.name == HTTP_CLIENT_PACKAGE and alias.asname
            }
        elif isinstance(node, ast.ImportFrom):
            source = _absolute_module(node, module)
            aliases |= {
                alias.asname or alias.name
                for alias in node.names
                if source and f"{source}.{alias.name}" == HTTP_CLIENT_PACKAGE
            }
    return frozenset(aliases)


def _is_package(node: ast.expr, aliases: frozenset[str]) -> bool:
    return (isinstance(node, ast.Name) and node.id in aliases) or (
        isinstance(node, ast.Attribute) and node.attr == "http_client"
    )


def _check_import_from(node: ast.ImportFrom, module: str | None) -> list[str]:
    source = _absolute_module(node, module)
    where = f"line {node.lineno}: from {'.' * node.level}{node.module or ''} import"
    findings: list[str] = []
    for alias in node.names:
        full = f"{source}.{alias.name}" if source else alias.name
        if source == HTTP_CLIENT_PACKAGE:
            if alias.name not in PUBLIC_SURFACE | {"*"}:
                findings.append(f"{where} {alias.name} (not in app.http_client.__all__)")
        elif source and _is_forbidden_module(source):
            findings.append(f"{where} {alias.name}")
        elif _is_forbidden_module(full) or _is_forbidden_name(alias.name):
            findings.append(f"{where} {alias.name}")
    return findings


def _check_call(node: ast.Call, aliases: frozenset[str]) -> list[str]:
    findings: list[str] = []
    function = node.func
    argument = node.args[0] if node.args else None
    text = argument.value if isinstance(argument, ast.Constant) else None
    if isinstance(text, str) and _is_dynamic_import(function) and _is_forbidden_module(text):
        findings.append(f"line {node.lineno}: dynamic import of {text}")
    if isinstance(function, ast.Name) and function.id in {"getattr", "hasattr"}:
        second = node.args[1] if len(node.args) > 1 else None
        if isinstance(second, ast.Constant) and isinstance(second.value, str):
            name = second.value
            if _is_forbidden_name(name) or (
                name in HTTP_CLIENT_SUBMODULES and _is_package(node.args[0], aliases)
            ):
                findings.append(f"line {node.lineno}: getattr(..., {name!r})")
    return findings


def find_network_access(source: str, module: str | None = None) -> list[str]:
    """Return a description of every way `source` could open a connection without the guard.

    `module` is the dotted name of the scanned module (`app.services.x`, or `app.pkg.__init__`
    for a package), used to resolve relative imports.
    """
    findings: list[str] = []
    tree = ast.parse(source)
    aliases = _package_aliases(tree, module)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            findings += [
                f"line {node.lineno}: import {alias.name}"
                for alias in node.names
                if _is_forbidden_module(alias.name)
            ]
        elif isinstance(node, ast.ImportFrom):
            findings += _check_import_from(node, module)
        elif isinstance(node, ast.Attribute):
            dotted = f"{node.value.id}.{node.attr}" if isinstance(node.value, ast.Name) else None
            if _is_forbidden_name(node.attr) or (dotted and _is_network_module(dotted)):
                findings.append(f"line {node.lineno}: .{node.attr}")
            elif node.attr in HTTP_CLIENT_SUBMODULES and _is_package(node.value, aliases):
                findings.append(f"line {node.lineno}: http_client.{node.attr} (internal module)")
        elif isinstance(node, ast.Call):
            findings += _check_call(node, aliases)
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


def _module_name(path: Path) -> str:
    base = BACKEND if BACKEND in path.parents else REPOSITORY
    return ".".join(path.relative_to(base).with_suffix("").parts)


def test_the_scan_covers_the_application() -> None:
    modules = _application_modules()

    assert BACKEND / "app" / "main.py" in modules
    assert not any(HTTP_CLIENT_MODULE in path.parents for path in modules)


def test_no_module_outside_the_http_client_opens_outgoing_connections() -> None:
    violations = {
        str(path.relative_to(REPOSITORY)): findings
        for path in _application_modules()
        if str(path.relative_to(REPOSITORY)) not in ALLOWED_MODULES
        and (findings := find_network_access(path.read_text(encoding="utf-8"), _module_name(path)))
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


def test_the_public_surface_exposes_no_networking_library_or_transport() -> None:
    import app.http_client as package

    assert set(package.__all__) == PUBLIC_SURFACE
    exposed = {name for name in PUBLIC_SURFACE if _is_forbidden_name(name)}
    assert exposed == set()
    for name in PUBLIC_SURFACE:
        value = getattr(package, name)
        assert not (isinstance(value, type(package)) and _is_network_module(value.__name__)), (
            f"app.http_client exports the module {value.__name__}"
        )


def test_every_http_client_module_declares_its_public_names() -> None:
    for path in sorted(HTTP_CLIENT_MODULE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        declared = [
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
            )
        ]
        assert declared, f"{path.name} must declare __all__"
        names = set(ast.literal_eval(declared[0].value))
        assert not {name for name in names if name in NETWORK_NAMES}, path.name
        assert "default_inner_transport" not in names


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
        # QA bypasses on #15 (FAIL, criterion 6): re-exports through the HTTP client package.
        "from app.http_client.url_guard import httpx2\nhttpx2.get('http://10.0.0.1')",
        "from app.http_client.client import httpx2",
        "from app.http_client.transport import httpx2",
        "from app.http_client.website_check import httpx2",
        "from app.http_client.website_check import ssl",
        "from app.http_client.url_guard import socket",
        "from app.http_client.transport import default_inner_transport",
        "from app.http_client.transport import GuardedTransport",
        "from app.http_client.transport import _DeadlineHTTPTransport",
        "from app.http_client import url_guard\nurl_guard.httpx2.get('http://10.0.0.1')",
        "from app.http_client import transport",
        "from app import http_client\nhttp_client.url_guard.httpx2.get('http://10.0.0.1')",
        "import app.http_client\napp.http_client.client.httpx2.get('http://10.0.0.1')",
        "import app.http_client.url_guard as guard",
        "import app.http_client as h\nh.transport",
        "import app.http_client as h\ngetattr(h, 'url_guard')",
        "from app import http_client\ngetattr(http_client.client, 'httpx2')",
        "from .http_client.url_guard import httpx2",
        "from ..http_client import transport",
        "from app.http_client import GuardedClient\nGuardedClient()._client._transport._inner",
        "import importlib\nimportlib.import_module('app.http_client.url_guard')",
        # QA bypasses on #15: asyncio and xmlrpc.
        "from asyncio import open_connection",
        "from asyncio import open_connection as connect",
        "import asyncio\nasyncio.get_running_loop().create_connection(object, 'example.com', 80)",
        "import asyncio as aio\naio.open_connection('example.com', 80)",
        "import xmlrpc.client",
        "from xmlrpc.client import ServerProxy\nServerProxy('http://example.com')",
        "from xmlrpc import client",
        "import xmlrpc\nxmlrpc.client.ServerProxy('http://example.com')",
        "import ssl\nssl.get_server_certificate(('example.com', 443))",
        "import smtplib",
    ],
)
def test_the_scan_detects_each_way_of_opening_a_connection(source: str) -> None:
    assert find_network_access(source, "app.services.sample")


@pytest.mark.parametrize(
    "source",
    [
        "import json",
        "from app.http_client import GuardedClient",
        "from app.http_client import check_website, WebsiteCheckResult, InvalidUrlError",
        "from app import http_client\nhttp_client.GuardedClient()",
        "from .http_client import GuardedClient",
        "import psycopg",
        "from urllib.parse import urljoin",
        "import http\nhttp.HTTPStatus.OK",
        "import ipaddress",
        "import asyncio\nasyncio.run(main())",
        "import ssl\nssl.create_default_context()",
    ],
)
def test_the_scan_allows_modules_that_open_no_connection(source: str) -> None:
    assert find_network_access(source, "app.sample") == []


def test_only_the_public_surface_of_the_http_client_may_be_imported() -> None:
    assert find_network_access("from app.http_client import system_resolver")
    assert find_network_access("from app.http_client import GuardedClient") == []
