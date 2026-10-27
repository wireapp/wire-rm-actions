"""scripts/lib.sh: the helpers every action script sources."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "scripts/lib.sh"


def _bash(snippet: str, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", f'set -euo pipefail; source "{LIB}"; {snippet}'],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", **env},
    )


def test_here_is_the_scripts_directory():
    result = _bash('echo "$here"')
    assert result.returncode == 0
    assert Path(result.stdout.strip()) == LIB.parent


def test_die_prints_an_error_annotation_and_exits_1():
    result = _bash('die "no such thing"; echo unreachable')
    assert result.returncode == 1
    assert result.stderr == "::error::no such thing\n"
    assert result.stdout == ""


def test_warn_prints_a_warning_annotation_and_goes_on():
    result = _bash('warn "careful"; echo after')
    assert result.returncode == 0
    assert result.stderr == "::warning::careful\n"
    assert result.stdout == "after\n"


def test_emit_writes_stdout_and_the_outputs_file(tmp_path: Path):
    outputs = tmp_path / "outputs"
    result = _bash('emit version 1.2.3; emit empty ""', GITHUB_OUTPUT=str(outputs))
    assert result.returncode == 0
    assert result.stdout == "version=1.2.3\nempty=\n"
    assert outputs.read_text() == "version=1.2.3\nempty=\n"


def test_emit_without_an_outputs_file_only_prints():
    result = _bash("emit version 1.2.3")
    assert result.returncode == 0
    assert result.stdout == "version=1.2.3\n"


def test_sha256_of_a_file(tmp_path: Path):
    f = tmp_path / "f"
    f.write_text("abc")
    result = _bash(f'sha256_of "{f}"')
    assert result.returncode == 0
    assert result.stdout.strip() == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_summary_appends_one_line_per_argument(tmp_path: Path):
    step_summary = tmp_path / "summary"
    result = _bash('summary "### Title" "" "- item"', GITHUB_STEP_SUMMARY=str(step_summary))
    assert result.returncode == 0
    assert result.stdout == ""
    assert step_summary.read_text() == "### Title\n\n- item\n"


def test_summary_without_a_step_summary_file_is_silent():
    result = _bash('summary "### Title"; echo after')
    assert result.returncode == 0
    assert result.stdout == "after\n"
