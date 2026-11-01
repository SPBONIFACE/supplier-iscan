"""Read-only, local MCP server over the repository's openapi.yaml (stdio, no network, no key).

Tools: list_operations, get_operation(method, path), get_schema(name). The file is read on every
call, so a change of the contract is seen without a restart. A missing or invalid file, an unknown
operation or an unknown schema is a tool error that names the file or the item; the server never
crashes on it.
"""

import os
from pathlib import Path
from typing import Any

import yaml
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
ENV_VAR = "OPENAPI_FILE"


def contract_path() -> Path:
    """OPENAPI_FILE if set, else openapi.yaml in the current directory (the repository root)."""
    return Path(os.environ.get(ENV_VAR) or "openapi.yaml")


def load_contract() -> dict[str, Any]:
    path = contract_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ToolError(f"Cannot read the contract file {path}: {exc.strerror or exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ToolError(f"The contract file {path} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("paths"), dict):
        raise ToolError(f"The contract file {path} is not an OpenAPI document (no 'paths' object)")
    return data


mcp = MCPServer(
    "supplier-iscan-contract",
    instructions="Read-only view of the API contract (openapi.yaml); read it before an endpoint.",
)


@mcp.tool()
def list_operations() -> list[dict[str, Any]]:
    """List every operation of the contract: method, path, operationId, summary, tags."""
    paths = load_contract()["paths"]
    return [
        {
            "method": method.upper(),
            "path": path,
            "operationId": op.get("operationId"),
            "summary": op.get("summary"),
            "tags": op.get("tags", []),
        }
        for path, item in paths.items()
        if isinstance(item, dict)
        for method, op in item.items()
        if method in HTTP_METHODS and isinstance(op, dict)
    ]


@mcp.tool()
def get_operation(method: str, path: str) -> dict[str, Any]:
    """Return the full contract entry of one operation, for example GET /health."""
    item = load_contract()["paths"].get(path)
    op = item.get(method.lower()) if isinstance(item, dict) else None
    if method.lower() not in HTTP_METHODS or not isinstance(op, dict):
        raise ToolError(f"Unknown operation {method.upper()} {path} in {contract_path()}")
    return {"method": method.upper(), "path": path, **op}


@mcp.tool()
def get_schema(name: str) -> dict[str, Any]:
    """Return one component schema by name, for example HealthStatus."""
    components = load_contract().get("components")
    schemas = components.get("schemas") if isinstance(components, dict) else None
    schema = schemas.get(name) if isinstance(schemas, dict) else None
    if not isinstance(schema, dict):
        raise ToolError(f"Unknown schema {name} in {contract_path()}")
    return schema


if __name__ == "__main__":
    mcp.run("stdio")
