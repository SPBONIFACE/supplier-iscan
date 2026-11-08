"""MCP server tests: a temporary contract file, no network, no key."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from mcp_server import server

REPO_CONTRACT = Path(__file__).resolve().parents[2] / "openapi.yaml"

SAMPLE = """
openapi: 3.1.0
paths:
  /health:
    get:
      operationId: getHealth
      summary: Liveness
      tags: [system]
      responses: {"200": {description: ok}}
    parameters: []
components:
  schemas:
    HealthStatus: {type: object}
"""


@pytest.fixture
def contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    f = tmp_path / "openapi.yaml"
    f.write_text(SAMPLE, encoding="utf-8")
    monkeypatch.setenv(server.ENV_VAR, str(f))
    return f


def test_list_operations(contract: Path) -> None:
    assert server.list_operations() == [
        {
            "method": "GET",
            "path": "/health",
            "operationId": "getHealth",
            "summary": "Liveness",
            "tags": ["system"],
        }
    ]


def test_get_operation_and_schema(contract: Path) -> None:
    assert server.get_operation("get", "/health")["operationId"] == "getHealth"
    assert server.get_schema("HealthStatus") == {"type": "object"}


def test_unknown_operation_names_it(contract: Path) -> None:
    with pytest.raises(ToolError, match=r"POST /health"):
        server.get_operation("POST", "/health")
    with pytest.raises(ToolError, match=r"GET /nope"):
        server.get_operation("GET", "/nope")


def test_unknown_schema_names_it(contract: Path) -> None:
    with pytest.raises(ToolError, match="Nope"):
        server.get_schema("Nope")


def test_missing_file_names_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(server.ENV_VAR, str(tmp_path / "absent.yaml"))
    with pytest.raises(ToolError, match="absent.yaml"):
        server.list_operations()


@pytest.mark.parametrize("content", ["a: [unclosed", "just a string", "paths: 3"])
def test_invalid_file_names_it(contract: Path, content: str) -> None:
    contract.write_text(content, encoding="utf-8")
    with pytest.raises(ToolError, match="openapi.yaml"):
        server.get_schema("HealthStatus")


def test_error_is_a_tool_error_result_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(server.ENV_VAR, str(tmp_path / "absent.yaml"))
    # Through the server's own call path: the error is a ToolError (reported to the client as
    # an isError result) naming the file, not an unexpected crash.
    call: Any = server.mcp.call_tool("list_operations", {})
    with pytest.raises(ToolError, match="absent.yaml") as info:
        asyncio.run(call)
    assert type(info.value) is ToolError


def test_repository_contract_is_served(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(server.ENV_VAR, str(REPO_CONTRACT))
    assert any(o["path"] == "/health" for o in server.list_operations())
    assert server.get_schema("HealthStatus")["type"] == "object"
