"""scripts/check-release-ref.sh: the refs of the reusable workflow name the release."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/check-release-ref.sh"
WORKFLOW = """\
      - uses: wireapp/wire-rm-actions/version@{ref}
      - uses: wireapp/wire-rm-actions/publish-chart@{ref}
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
"""


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True)


def _workflow(tmp_path: Path, ref: str, name: str = "dev-build.yml") -> Path:
    path = tmp_path / ".github/workflows" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(WORKFLOW.format(ref=ref))
    return path


def test_refs_at_the_release_pass(tmp_path: Path):
    _workflow(tmp_path, "v1.2.0")
    result = _run("v1.2.0", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "every wireapp/wire-rm-actions ref is @v1.2.0" in result.stdout


@pytest.mark.parametrize("ref", ["dev", "v1.1.0", "3d3c42e5aac5ba805825da76410c181273ba90b1"])
def test_another_ref_fails_and_is_listed(tmp_path: Path, ref: str):
    _workflow(tmp_path, ref)
    result = _run("v1.2.0", cwd=tmp_path)
    assert result.returncode == 1
    assert "make release-prep VERSION=v1.2.0" in result.stderr
    assert f"version@{ref}" in result.stderr


def test_templates_are_checked_when_present(tmp_path: Path):
    _workflow(tmp_path, "v1.2.0")
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates/repair.yml").write_text(WORKFLOW.format(ref="dev"))
    result = _run("v1.2.0", cwd=tmp_path)
    assert result.returncode == 1
    assert "templates/repair.yml" in result.stderr


def test_a_pre_release_tag_is_accepted(tmp_path: Path):
    _workflow(tmp_path, "v1.2.0-rc.1")
    assert _run("v1.2.0-rc.1", cwd=tmp_path).returncode == 0


@pytest.mark.parametrize("version", ["1.2.0", "v1.2", "v1.2.0-rc.0", ""])
def test_a_bad_version_is_a_usage_error(tmp_path: Path, version: str):
    _workflow(tmp_path, "v1.2.0")
    assert _run(version, cwd=tmp_path).returncode == 64


def test_given_files_only(tmp_path: Path):
    other = _workflow(tmp_path, "v1.2.0", name="other.yml")
    result = _run("v1.2.0", str(other), cwd=tmp_path)
    assert result.returncode == 0, result.stderr


def test_a_file_without_refs_fails(tmp_path: Path):
    path = _workflow(tmp_path, "v1.2.0")
    path.write_text("- uses: actions/checkout@abc # v7\n")
    assert _run("v1.2.0", cwd=tmp_path).returncode == 1
