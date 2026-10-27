"""scripts/compatibility.sh: the ADR-0020 compatibility file checked and written
as JSON, in its own shape and in the provides / requires shape of the
v1alpha1 manifest."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/compatibility.sh"
FIXTURES = ROOT / "testdata/compatibility"


def _run(cwd: Path, out: Path, **env: str) -> subprocess.CompletedProcess:
    clean = {k: v for k, v in os.environ.items() if k not in ("FILE", "OUTPUT_DIR", "GITHUB_OUTPUT")}
    return subprocess.run(
        ["bash", str(SCRIPT)], cwd=cwd, env={**clean, "OUTPUT_DIR": str(out), **env},
        capture_output=True, text=True,
    )


OUTPUTS = ("file", "compatibility", "manifest-compatibility")


def _outputs(result: subprocess.CompletedProcess) -> dict[str, str]:
    pairs = (line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    return {key: value for key, value in pairs if key in OUTPUTS}


def _errors(result: subprocess.CompletedProcess) -> list[str]:
    return [line for line in result.stderr.splitlines() if line.startswith("::error::")]


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text())


def test_new_file_written_in_both_shapes(tmp_path: Path):
    result = _run(ROOT, tmp_path, FILE=str(FIXTURES / "ok-full.yaml"))
    assert result.returncode == 0, result.stderr
    out = _outputs(result)
    assert _load(out["compatibility"])["providesApis"][0]["api"] == "wire-server/client-api"
    assert _load(out["manifest-compatibility"]) == {
        "provides": [
            {"interface": "wire-server/client-api", "supported": "4-6", "deprecated": "4", "development": "7"},
            {"interface": "wire-server/scim-api", "supported": "2.0.0"},
        ],
        "requires": [
            {"interface": "wire-server/admin-api", "range": "^0", "reason": "Informational, version 0."},
            {"interface": "wire-server/client-api", "range": "1,2,3,5", "class": "mandatory",
             "reason": "Negotiated through /api-version."},
            {"capability": "postgresql", "range": ">=17.0.0", "class": "mandatory"},
            {"platform": "ingress-nginx", "range": "*", "class": "optional", "reason": "ingress.enabled."},
            {"platform": "kubernetes", "range": ">=1.29.0"},
        ],
        "includes": [{"component": "sftd", "version": "4.1.0", "reason": "Shipped inside."}],
    }


@pytest.mark.parametrize("name", ["ok-empty.yaml", "ok-my-component.yaml", "ok-client.yaml"])
def test_component_files_pass(tmp_path: Path, name: str):
    result = _run(ROOT, tmp_path, FILE=str(FIXTURES / name))
    assert result.returncode == 0, result.stderr
    assert "valid compatibility file" in result.stdout


def test_client_api_becomes_a_range(tmp_path: Path):
    out = _outputs(_run(ROOT, tmp_path, FILE=str(FIXTURES / "ok-client.yaml")))
    requires = _load(out["manifest-compatibility"])["requires"]
    assert requires[0] == {
        "interface": "wire-server/client-api", "range": "1-16", "class": "mandatory",
        "reason": "Backend API, highest common version negotiated at start.",
    }


def test_default_reads_the_publication_folder(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "publication").mkdir(parents=True)
    shutil.copy(FIXTURES / "ok-empty.yaml", repo / "publication/compatibility.yaml")
    result = _run(repo, tmp_path / "out")
    assert result.returncode == 0, result.stderr
    assert _outputs(result)["file"] == "publication/compatibility.yaml"
    assert "::warning::" not in result.stdout


def test_the_former_root_file_is_refused(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copy(FIXTURES / "bad-former.yaml", repo / "compatibility.yaml")
    result = _run(repo, tmp_path / "out")
    assert result.returncode == 1
    assert "the root compatibility.yaml (provides, requires) is the former layout, move it to publication/compatibility.yaml" in _errors(result)[0]
    assert not (tmp_path / "out/manifest-compatibility.json").exists()



def test_no_file_fails(tmp_path: Path):
    result = _run(tmp_path, tmp_path / "out")
    assert result.returncode == 1
    assert "no compatibility file" in _errors(result)[0]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("bad-former.yaml", "the former format (provides, requires) is not read any more"),
        ("bad-unknown.yaml", "not the ADR-0020 format"),
        ("bad-syntax.yaml", "not valid YAML"),
        ("bad-no-includes.yaml", "includes must be a list ([] when empty)"),
    ],
)
def test_invalid_file_fails_with_the_error(tmp_path: Path, name: str, expected: str):
    file = FIXTURES / name
    result = _run(ROOT, tmp_path, FILE=str(file))
    assert result.returncode == 1
    assert any(e.startswith(f"::error::{file}: {expected}") for e in _errors(result)), result.stderr
    assert not (tmp_path / "manifest-compatibility.json").exists()


def test_every_entry_error_is_printed(tmp_path: Path):
    file = FIXTURES / "bad-entries.yaml"
    result = _run(ROOT, tmp_path, FILE=str(file))
    assert result.returncode == 1
    assert [e.removeprefix(f"::error::{file}: ") for e in _errors(result)] == [
        "unknown key extra",
        "providesApis[0].versions.supported must be a list of API versions",
        "providesApis[1].api is required",
        "providesApis[1].versions must be {supported, deprecated, development} or a list of versions",
        "consumesApis[0] is optional and needs a reason",
        "consumesApis[1].class must be mandatory, optional or alternative",
        "dependsOn[0] must name exactly one of resource, component or platform",
        "dependsOn[1].range is required",
        "includes[0] needs exactly one of version or range",
        "includes[0] is unconditional and has no class",
        "includes[0].reason is required",
        "invalid compatibility file",
    ]
