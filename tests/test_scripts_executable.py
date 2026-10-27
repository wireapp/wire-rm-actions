"""Every script an action runs is executable in git: a composite action calls
"$GITHUB_ACTION_PATH/../scripts/<name>.sh" directly, and a 100644 file fails
with "Permission denied" on the runner."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RUN_RE = re.compile(r"scripts/([A-Za-z0-9_.-]+\.sh)")
SCRIPTS = sorted({m for action in ROOT.glob("*/action.yml") for m in RUN_RE.findall(action.read_text())})


def _git_mode(path: str) -> str:
    out = subprocess.run(["git", "ls-files", "-s", path], cwd=ROOT, capture_output=True, text=True, check=True)
    return out.stdout.split()[0] if out.stdout else ""


def test_actions_run_scripts():
    assert SCRIPTS


@pytest.mark.parametrize("script", SCRIPTS)
def test_the_script_is_executable_in_git(script: str):
    assert _git_mode(f"scripts/{script}") == "100755", f"scripts/{script} is not executable in git"
