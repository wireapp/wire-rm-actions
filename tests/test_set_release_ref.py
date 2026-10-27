"""scripts/set-release-ref.sh on a copy of the reusable workflow."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/set-release-ref.sh"
WORKFLOW = ROOT / ".github/workflows/dev-build.yml"
REF = re.compile(r"uses: wireapp/wire-rm-actions/[^@\s]+@(\S+)")


@pytest.fixture
def workflow(tmp_path: Path) -> Path:
    copy = tmp_path / "dev-build.yml"
    shutil.copy(WORKFLOW, copy)
    return copy


def _run(workflow: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        env={**os.environ, "WORKFLOW": str(workflow)},
        capture_output=True,
        text=True,
    )


def test_points_every_action_at_the_version(workflow: Path):
    before = workflow.read_text()
    result = _run(workflow, "v0.1.0")
    assert result.returncode == 0, result.stderr
    after = workflow.read_text()
    assert REF.findall(after) == ["v0.1.0"] * len(REF.findall(before))
    assert len(REF.findall(after)) == 4
    # Nothing but the refs changes.
    assert REF.sub("REF", after) == REF.sub("REF", before).replace("@dev", "@v0.1.0")


def test_replaces_a_previous_release(workflow: Path):
    assert _run(workflow, "v0.1.0").returncode == 0
    assert _run(workflow, "v0.2.0").returncode == 0
    assert set(REF.findall(workflow.read_text())) == {"v0.2.0"}


@pytest.mark.parametrize("version", ["", "0.1.0", "v0.1", "v01.0.0", "v0.1.0-rc.1", "main"])
def test_refuses_a_non_release_version(workflow: Path, version: str):
    before = workflow.read_text()
    assert _run(workflow, version).returncode == 64
    assert workflow.read_text() == before


def test_fails_without_any_ref(tmp_path: Path):
    empty = tmp_path / "other.yml"
    empty.write_text("name: other\n")
    result = _run(empty, "v0.1.0")
    assert result.returncode == 1
    assert "no wireapp/wire-rm-actions ref" in result.stderr
