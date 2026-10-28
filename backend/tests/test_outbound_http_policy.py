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
  library and the inner transport live) may not be imported or reached at all;
- outside its own package, any use of a module in `ALLOWED_MODULES` (an unguarded fetcher kept for
  fixed hosts that are not supplier sites): importing it or any name it defines, through an alias,
  a relative import, a re-export by its package, a star import or an attribute
  (`registries.httpx2_fetch.Httpx2Fetch`). Inside its package its names may be used but not
  renamed, so they cannot leave the package under another name.

Fetches to supplier sites go through `app.http_client.GuardedClient` and `check_website`. A static
scan cannot see code built at run time (`exec`, computed module names); review catches those.

Database drivers are not networking libraries in this sense and are not listed. The official LLM
SDKs (`anthropic`, `openai`, `google.genai`, `mistralai`, `perplexity`) are listed (#11): they
open connections, to the fixed endpoint of an approved provider configuration and never to a user
URL, and are imported only by the provider adapters of `app/providers/adapters/`, which are in
`ALLOWED_MODULES` and usable only inside their package (the registry reaches them through
`app.providers.adapters.ADAPTERS`, after the approved-configuration checks).
"""

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
REPOSITORY = BACKEND.parent
SCANNED_ROOTS = [BACKEND / "app", BACKEND / "worker", REPOSITORY / "worker"]
HTTP_CLIENT_MODULE = BACKEND / "app" / "http_client"
HTTP_CLIENT_PACKAGE = "app.http_client"
PROVIDER_ADAPTERS = BACKEND / "app" / "providers" / "adapters"

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
        # Official LLM SDKs (#11): only in the provider adapters (ALLOWED_MODULES).
        "anthropic",
        "google.genai",
        "mistralai",
        "openai",
        "perplexity",
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
        "_GuardedClient__client",
        "_inner",
        "_network_backend",
        "_pool",
    }
)

# A module outside app/http_client that must open connections itself (to a host that is not a
# supplier site) is listed here with its reason, and reviewed like any security change. Such a
# module is usable only inside its own package (see `_allowed_module_findings`): it is not a way
# around the guard for the rest of the application.
ALLOWED_MODULES: dict[str, str] = {
    "backend/app/registries/httpx2_fetch.py": (
        "#14: the registries' single network module, to the fixed public hosts of Wikidata and "
        "GLEIF only; to be switched to the guarded client in #16."
    ),
    "backend/app/providers/adapters/anthropic_adapter.py": (
        "#11: provider adapter on the official SDK, to the fixed endpoint of an approved "
        "provider configuration only (never a user URL); reached only through "
        "app.providers.adapters.ADAPTERS by the registry, after the configuration checks."
    ),
    "backend/app/providers/adapters/google_adapter.py": (
        "#11: provider adapter on the official SDK, to the fixed endpoint of an approved "
        "provider configuration only (never a user URL); reached only through "
        "app.providers.adapters.ADAPTERS by the registry, after the configuration checks."
    ),
    "backend/app/providers/adapters/mistral_adapter.py": (
        "#11: provider adapter on the official SDK, to the fixed endpoint of an approved "
        "provider configuration only (never a user URL); reached only through "
        "app.providers.adapters.ADAPTERS by the registry, after the configuration checks."
    ),
    "backend/app/providers/adapters/openai_adapter.py": (
        "#11: provider adapter on the official SDK, to the fixed endpoint of an approved "
        "provider configuration only (never a user URL); reached only through "
        "app.providers.adapters.ADAPTERS by the registry, after the configuration checks."
    ),
    "backend/app/providers/adapters/perplexity_adapter.py": (
        "#11: provider adapter on the official SDK, to the fixed endpoint of an approved "
        "provider configuration only (never a user URL); reached only through "
        "app.providers.adapters.ADAPTERS by the registry, after the configuration checks."
    ),
}


@dataclass(frozen=True)
class _AllowedModule:
    """An allowed module, its package, and the names it defines (read without importing it)."""

    name: str  # app.registries.httpx2_fetch
    package: str  # app.registries
    names: frozenset[str]  # its own name, and every top-level name it defines or lists in __all__

    def is_inside(self, module: str | None) -> bool:
        return module is not None and module.startswith(self.package + ".")

    def is_module(self, name: str) -> bool:
        return name == self.name or name.startswith(self.name + ".")

    def is_in_package(self, name: str) -> bool:
        return name == self.package or name.startswith(self.package + ".")


def _defined_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            bound = {target.id for target in targets if isinstance(target, ast.Name)}
            names |= bound
            if "__all__" in bound and node.value is not None:
                names |= set(ast.literal_eval(node.value))
    return names - {"__all__"}


def _allowed_module(relative_path: str) -> _AllowedModule:
    path = REPOSITORY / relative_path
    parts = path.relative_to(BACKEND).with_suffix("").parts
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return _AllowedModule(
        name=".".join(parts),
        package=".".join(parts[:-1]),
        names=frozenset(_defined_names(tree) | {parts[-1]}),
    )


ALLOWED = tuple(_allowed_module(path) for path in ALLOWED_MODULES)


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


def _check_allowed_import_from(
    node: ast.ImportFrom, module: str | None, allowed: _AllowedModule
) -> list[str]:
    source = _absolute_module(node, module) or ""
    inside = allowed.is_inside(module)
    findings: list[str] = []
    for alias in node.names:
        names_it = (
            allowed.is_module(source)
            or allowed.is_module(f"{source}.{alias.name}")
            or alias.name in allowed.names
        )
        star_from_package = alias.name == "*" and allowed.is_in_package(source)
        where = f"line {node.lineno}: from {source} import {alias.name}"
        if not inside and (names_it or star_from_package):
            findings.append(f"{where} ({allowed.name} outside {allowed.package})")
        elif inside and alias.asname and names_it:
            findings.append(f"{where} as {alias.asname} ({allowed.name} renamed)")
    return findings


def _allowed_module_findings(node: ast.AST, module: str | None) -> list[str]:
    """Uses of an allowed module outside its own package, or renamed inside it."""
    findings: list[str] = []
    for allowed in ALLOWED:
        if isinstance(node, ast.ImportFrom):
            findings += _check_allowed_import_from(node, module, allowed)
            continue
        if allowed.is_inside(module):
            continue
        if isinstance(node, ast.Import):
            findings += [
                f"line {node.lineno}: import {alias.name} ({allowed.name} outside its package)"
                for alias in node.names
                if allowed.is_module(alias.name)
            ]
        elif isinstance(node, ast.Attribute) and node.attr in allowed.names:
            findings.append(f"line {node.lineno}: .{node.attr} ({allowed.name})")
        elif isinstance(node, ast.Call):
            texts = [arg.value for arg in node.args[:2] if isinstance(arg, ast.Constant)]
            findings += [
                f"line {node.lineno}: {text!r} ({allowed.name})"
                for text in texts
                if isinstance(text, str) and (allowed.is_module(text) or text in allowed.names)
            ]
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
        findings += _allowed_module_findings(node, module)
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


def _violations(sources: dict[Path, str]) -> dict[str, list[str]]:
    """The scan's findings per module; an allowed module's own file is not scanned."""
    return {
        relative: findings
        for path, source in sources.items()
        if (relative := str(path.relative_to(REPOSITORY))) not in ALLOWED_MODULES
        and (findings := find_network_access(source, _module_name(path)))
    }


def _application_sources() -> dict[Path, str]:
    return {path: path.read_text(encoding="utf-8") for path in _application_modules()}


def test_no_module_outside_the_http_client_opens_outgoing_connections() -> None:
    violations = _violations(_application_sources())

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
        # #11: the LLM SDKs are networking libraries outside the provider adapters.
        "import anthropic",
        "import openai",
        "from openai import OpenAI",
        "from google import genai",
        "import google.genai",
        "from mistralai.client import Mistral",
        "import perplexity",
        "__import__('anthropic')",
        # ... and the adapters cannot be used outside their package.
        "from app.providers.adapters.google_adapter import make_client",
        "from app.providers.adapters import google_adapter",
        "import app.providers.adapters.openai_adapter",
        "from app.providers.adapters.mistral_adapter import *",
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


# QA's bypass on #15 (FAIL, criterion 6, third round): a module elsewhere using the registries'
# unguarded fetcher, which accepts any URL.
QA_PROBE_CRAWLER = """\
from app.registries.httpx2_fetch import Httpx2Fetch
async def fetch_supplier_page(url): return (await Httpx2Fetch(10.0)(url, {}, {})).body
"""


def test_the_allowed_module_and_its_names_are_known_to_the_scan() -> None:
    fetcher, *adapters = ALLOWED

    assert {adapter.package for adapter in adapters} == {"app.providers.adapters"}
    assert {"make_client", "build_structuring"} <= adapters[0].names
    assert fetcher.name == "app.registries.httpx2_fetch"
    assert fetcher.package == "app.registries"
    assert {"httpx2_fetch", "Httpx2Fetch"} <= fetcher.names


def test_a_module_elsewhere_using_the_allowed_fetcher_fails_the_scan() -> None:
    probe = BACKEND / "app" / "qa_probe_crawler.py"
    sources = {**_application_sources(), probe: QA_PROBE_CRAWLER}

    violations = _violations(sources)

    assert list(violations) == ["backend/app/qa_probe_crawler.py"]


OUTSIDE = "app.services.crawler"


@pytest.mark.parametrize(
    ("source", "module"),
    [
        (QA_PROBE_CRAWLER, "app.qa_probe_crawler"),
        ("from app.registries.httpx2_fetch import Httpx2Fetch", OUTSIDE),
        ("from app.registries.httpx2_fetch import Httpx2Fetch as Fetch", OUTSIDE),
        ("from app.registries.httpx2_fetch import *", OUTSIDE),
        ("import app.registries.httpx2_fetch", OUTSIDE),
        ("import app.registries.httpx2_fetch as f\nf.Httpx2Fetch(1.0)", OUTSIDE),
        ("from app.registries import httpx2_fetch", OUTSIDE),
        ("from app.registries import httpx2_fetch as f", OUTSIDE),
        ("from app import registries\nregistries.httpx2_fetch.Httpx2Fetch", OUTSIDE),
        ("import app.registries as r\nr.httpx2_fetch", OUTSIDE),
        ("from app.registries import service\nservice.Httpx2Fetch", OUTSIDE),
        # A re-export through the package or one of its modules.
        ("from app.registries import Httpx2Fetch", OUTSIDE),
        ("from app.registries.service import Httpx2Fetch", OUTSIDE),
        ("from app.registries.service import *", OUTSIDE),
        ("from app.registries import *", OUTSIDE),
        # Relative imports, resolved against the module's own name.
        ("from .registries.httpx2_fetch import Httpx2Fetch", "app.qa_probe_crawler"),
        ("from .registries import httpx2_fetch", "app.qa_probe_crawler"),
        ("from ..registries.httpx2_fetch import Httpx2Fetch", OUTSIDE),
        ("from ..registries import Httpx2Fetch", OUTSIDE),
        # Literal names given to getattr or import_module.
        ("import importlib\nimportlib.import_module('app.registries.httpx2_fetch')", OUTSIDE),
        ("import app.registries as r\ngetattr(r, 'httpx2_fetch')", OUTSIDE),
        ("from app.registries import service\ngetattr(service, 'Httpx2Fetch')", OUTSIDE),
        # Inside the package, the fetcher may not leave under another name.
        ("from app.registries.httpx2_fetch import Httpx2Fetch as F", "app.registries.service"),
        ("from .httpx2_fetch import Httpx2Fetch as Fetch", "app.registries.service"),
        ("from . import httpx2_fetch as f", "app.registries.__init__"),
    ],
)
def test_the_allowed_fetcher_cannot_be_used_outside_its_package(source: str, module: str) -> None:
    assert find_network_access(source, module)


@pytest.mark.parametrize(
    ("source", "module"),
    [
        ("from app.registries.httpx2_fetch import Httpx2Fetch", "app.registries.service"),
        ("from .httpx2_fetch import Httpx2Fetch", "app.registries.service"),
        ("from . import httpx2_fetch", "app.registries.__init__"),
        ("from app.registries.http import FetchError", "app.registries.gleif"),
        # The registries' public surface stays usable from elsewhere.
        ("from app.registries import RegistrySearchService", "app.main"),
        ("from app.registries import build_registry_service, load_registry_settings", "app.main"),
        ("from app.registries.models import RegistryCandidate", "app.api.suppliers"),
    ],
)
def test_the_allowed_fetcher_is_usable_inside_its_package(source: str, module: str) -> None:
    assert find_network_access(source, module) == []


def test_the_guarded_clients_raw_client_is_an_internal_name() -> None:
    assert find_network_access(
        "from app.http_client import GuardedClient\nGuardedClient()._GuardedClient__client.get(u)",
        "app.services.sample",
    )


def test_only_the_registry_reaches_the_provider_adapters() -> None:
    # #11: the adapter package is entered only through the registry, which checks the
    # configuration (approved, key set) before building an adapter.
    importers = sorted(
        str(path.relative_to(REPOSITORY))
        for path, source in _application_sources().items()
        if PROVIDER_ADAPTERS not in path.parents and "app.providers.adapters" in source
    )

    assert importers == ["backend/app/providers/registry.py"]
