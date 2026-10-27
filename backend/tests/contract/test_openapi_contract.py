"""Contract test: openapi.yaml is valid OpenAPI 3.1, and the API answers as it describes."""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator
from jsonschema.validators import validator_for
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from tests.support import make_client

HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE.parents[2] / "openapi.yaml"
META_SCHEMA_PATH = HERE / "openapi-3.1-schema.json"
CONTRACT_URI = "urn:supplier-iscan:openapi"


def load_contract() -> dict[str, Any]:
    contract: dict[str, Any] = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    return contract


def response_validator(contract: dict[str, Any], path: str, method: str, status: int) -> Any:
    """Validator for the JSON body of one documented response, with $refs resolved.

    The response may be inline or a `$ref` to components/responses.
    """
    pointer_path = path.replace("~", "~0").replace("/", "~1")
    response_pointer = f"#/paths/{pointer_path}/{method}/responses/{status}"
    response = contract["paths"][path][method]["responses"][str(status)]
    if "$ref" in response:
        response_pointer = response["$ref"]
    pointer = f"{response_pointer}/content/application~1json/schema"
    registry: Registry[Any] = Registry().with_resource(
        CONTRACT_URI, Resource.from_contents(contract, default_specification=DRAFT202012)
    )
    return Draft202012Validator({"$ref": CONTRACT_URI + pointer}, registry=registry)


def test_contract_is_valid_openapi_3_1() -> None:
    contract = load_contract()
    meta_schema = json.loads(META_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator_class = validator_for(meta_schema)
    validator_class.check_schema(meta_schema)

    assert str(contract["openapi"]).startswith("3.1.")
    validator_class(meta_schema).validate(contract)


def test_meta_schema_rejects_an_invalid_document() -> None:
    # Guards the test above: a document without `info` is not valid OpenAPI 3.1.
    meta_schema = json.loads(META_SCHEMA_PATH.read_text(encoding="utf-8"))
    invalid = {key: value for key, value in load_contract().items() if key != "info"}

    assert not validator_for(meta_schema)(meta_schema).is_valid(invalid)


def test_contract_schemas_are_valid_json_schemas() -> None:
    for schema in load_contract()["components"]["schemas"].values():
        Draft202012Validator.check_schema(schema)


def test_contract_describes_health_with_200_and_503() -> None:
    responses = load_contract()["paths"]["/health"]["get"]["responses"]

    assert set(responses) == {"200", "503"}


@pytest.mark.parametrize(
    ("database_available", "expected_status"),
    [(True, 200), (False, 503)],
)
def test_health_responses_match_the_contract(
    database_available: bool, expected_status: int
) -> None:
    contract = load_contract()
    response = make_client(database_check=lambda: database_available).get("/health")

    assert response.status_code == expected_status
    assert str(response.status_code) in contract["paths"]["/health"]["get"]["responses"]
    assert response.headers["content-type"].startswith("application/json")
    response_validator(contract, "/health", "get", response.status_code).validate(response.json())


def test_contract_rejects_a_body_that_breaks_it() -> None:
    # Guards the test itself: the validator must catch a body the contract does not allow.
    validator = response_validator(load_contract(), "/health", "get", 200)

    assert not validator.is_valid({"api": "available", "database": "maybe"})
    assert not validator.is_valid({"api": "available"})
    assert not validator.is_valid({"api": "available", "database": "available", "extra": 1})
