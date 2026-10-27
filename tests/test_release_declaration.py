"""scripts/release-declaration.sh: the jq check of a release declaration against
the vendored v1alpha2 schema, cross-checked with the jsonschema package."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/release-declaration.sh"
SCHEMA = ROOT / "schemas/wire.component-release-v1alpha2.json"
SCHEMAS = (SCHEMA,)
FIXTURES = ROOT / "testdata/release-declaration"
VALID = sorted(FIXTURES.glob("valid*.json"))
INVALID = sorted(FIXTURES.glob("invalid*.json"))

# The keywords the jq check interprets; any other keyword in the schema would be
# silently ignored by the script, so the schema must stay within this set.
SUPPORTED_KEYWORDS = {
    "$schema", "$id", "title", "description",
    "type", "const", "enum", "required", "properties", "additionalProperties",
    "items", "pattern", "minLength", "maxLength",
}


def _run(*files: Path, **env: str) -> subprocess.CompletedProcess:
    clean = {k: v for k, v in os.environ.items() if k not in ("FILE", "COMPONENT", "VERSION", "SCHEMA")}
    return subprocess.run(
        ["bash", str(SCRIPT), *map(str, files)], env={**clean, **env}, capture_output=True, text=True
    )


def _errors(result: subprocess.CompletedProcess) -> list[str]:
    return [line for line in result.stderr.splitlines() if line.startswith("::error::")]


def _subschemas(schema: dict):
    yield schema
    for sub in schema.get("properties", {}).values():
        yield from _subschemas(sub)
    if "items" in schema:
        yield from _subschemas(schema["items"])


def test_fixtures_exist():
    assert len(VALID) >= 1 and len(INVALID) >= 4


@pytest.mark.parametrize("file", VALID, ids=lambda p: p.name)
def test_valid_declaration_passes(file: Path):
    result = _run(file)
    assert result.returncode == 0, result.stderr
    assert _errors(result) == []
    assert "valid release declaration of my-component" in result.stdout


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("invalid-missing-section.json", "$: missing required key migrations"),
        ("invalid-bad-enum.json", '$.migrations[0].kind: must be one of ["schema","data","manual"]'),
        ("invalid-configuration-without-description.json", "$.configuration[0]: missing required key description"),
        ("invalid-schema-version.json", '$.schemaVersion: must be "wire.component-release/v1alpha2"'),
        ("invalid-v1alpha2-change-kind.json", '$.changes[0].kind: must be one of ["added","changed","deprecated","removed","fixed","security"]'),
        ("invalid-v1alpha2-prerelease-version.json", "$.version: must match ^[0-9]+\\.[0-9]+\\.[0-9]+$"),
        ("invalid-types-and-keys.json", "$.changes: must be array, not string"),
    ],
)
def test_invalid_declaration_fails_with_the_error(name: str, expected: str):
    file = FIXTURES / name
    result = _run(file)
    assert result.returncode == 1
    assert f"::error::{file}: {expected}" in _errors(result)
    assert _errors(result)[-1] == f"::error::{file}: invalid release declaration"


def test_every_error_is_printed():
    result = _run(FIXTURES / "invalid-bad-enum.json")
    assert [e.split(": ", 1)[1] for e in _errors(result)] == [
        '$.migrations[0].kind: must be one of ["schema","data","manual"]',
        '$.configuration[0].change: must be one of ["added","removed","changed"]',
        "invalid release declaration",
    ]


def test_stops_at_the_first_invalid_document():
    result = _run(VALID[0], INVALID[0], INVALID[1])
    assert result.returncode == 1
    assert VALID[0].name in result.stdout
    assert INVALID[0].name in result.stderr and INVALID[1].name not in result.stderr


def test_file_from_the_environment():
    result = _run(FILE=str(VALID[0]))
    assert result.returncode == 0, result.stderr
    assert _run().returncode != 0


@pytest.mark.parametrize("content", ["{not json", ""])
def test_not_json_fails(tmp_path: Path, content: str):
    file = tmp_path / "declaration.json"
    file.write_text(content)
    result = _run(file)
    assert result.returncode == 1
    assert _errors(result) == [f"::error::{file}: not a JSON document"]


def test_missing_file_fails(tmp_path: Path):
    result = _run(tmp_path / "missing.json")
    assert result.returncode == 1
    assert "does not exist" in result.stderr


def test_component_and_version_must_match():
    file = FIXTURES / "valid.json"
    assert _run(file, COMPONENT="my-component", VERSION="4.25.0").returncode == 0
    assert _run(file, COMPONENT="my-component").returncode == 0
    assert _run(file, VERSION="4.25.0").returncode == 0
    result = _run(file, COMPONENT="wire-server", VERSION="4.25.1")
    assert result.returncode == 1
    assert f"::error::{file}: component is 'my-component', expected 'wire-server'" in _errors(result)
    assert f"::error::{file}: version is '4.25.0', expected '4.25.1'" in _errors(result)


def test_document_values_cannot_start_a_workflow_command(tmp_path: Path):
    doc = json.loads((FIXTURES / "valid.json").read_text())
    doc["component"] = "x\n::warning::injected"
    doc["version"] = "1.0.0\n::warning::injected"
    file = tmp_path / "declaration.json"
    file.write_text(json.dumps(doc))
    result = _run(file, COMPONENT="my-component", VERSION="4.25.0")
    assert result.returncode == 1
    assert not any(line.startswith("::warning::") for line in result.stderr.splitlines())
    assert f"::error::{file}: component is 'x\\n::warning::injected', expected 'my-component'" in _errors(result)
    assert f"::error::{file}: version is '1.0.0\\n::warning::injected', expected '4.25.0'" in _errors(result)


def test_component_check_also_reported_on_an_invalid_document():
    file = FIXTURES / "invalid-missing-section.json"
    result = _run(file, COMPONENT="wire-server")
    assert "missing required key migrations" in result.stderr
    assert "component is 'my-component', expected 'wire-server'" in result.stderr


# Cross-checks against the jsonschema package: the jq check must agree with a
# real Draft 2020-12 validator on every fixture, error for error (by path).


def _jsonschema_paths(doc: dict) -> list[str]:
    validator = jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text()))
    # By path: jsonschema reports all the unexpected keys of an object in one error,
    # the jq check one error per key.
    return sorted({e.json_path for e in validator.iter_errors(doc)})


def _jq_paths(file: Path) -> list[str]:
    result = _run(file)
    return sorted({e.split(": ", 2)[1] for e in _errors(result) if not e.endswith("invalid release declaration")})


@pytest.mark.parametrize("file", VALID + INVALID, ids=lambda p: p.name)
def test_jq_agrees_with_jsonschema(file: Path):
    doc = json.loads(file.read_text())
    expected = _jsonschema_paths(doc)
    assert _jq_paths(file) == expected
    assert (_run(file).returncode == 0) == (expected == [])


@pytest.mark.parametrize("schema", SCHEMAS, ids=lambda p: p.name)
def test_schema_is_a_valid_draft_2020_12_schema(schema: Path):
    jsonschema.Draft202012Validator.check_schema(json.loads(schema.read_text()))


@pytest.mark.parametrize("schema", SCHEMAS, ids=lambda p: p.name)
def test_schema_uses_only_the_keywords_jq_interprets(schema: Path):
    schema = json.loads(schema.read_text())
    for sub in _subschemas(schema):
        assert set(sub) <= SUPPORTED_KEYWORDS, sorted(set(sub) - SUPPORTED_KEYWORDS)


def test_v1alpha2_is_read_without_warning():
    result = _run(FIXTURES / "valid-v1alpha2.json")
    assert result.returncode == 0, result.stderr
    assert "::warning::" not in result.stdout
