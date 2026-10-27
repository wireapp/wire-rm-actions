"""The fake gh (tests/fake_gh.py) first on PATH, shared by the ci-gate and draft-release tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
REPO = "wireapp/example"


class FakeGH:
    def __init__(self, tmp_path: Path):
        self.dir = tmp_path / "gh"
        self.dir.mkdir()
        self.state_file = self.dir / "state.json"
        self.log_file = self.dir / "calls.log"
        self.log_file.touch()
        bin_dir = self.dir / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(f'#!/bin/sh\nexec "{sys.executable}" -I "{ROOT / "tests/fake_gh.py"}" "$@"\n')
        gh.chmod(0o755)
        self.bin = bin_dir
        self.state = {"repo": REPO}
        self.save()

    def save(self) -> None:
        self.state_file.write_text(json.dumps(self.state))

    def load(self) -> dict:
        self.state = json.loads(self.state_file.read_text())
        return self.state

    def calls(self) -> list[list[str]]:
        return [json.loads(line) for line in self.log_file.read_text().splitlines()]

    def run(self, script: str, cwd: Path, keys: tuple[str, ...], **env: str) -> subprocess.CompletedProcess:
        self.save()
        clean = {k: v for k, v in os.environ.items() if k not in keys and not k.startswith("GITHUB_")}
        full = {
            **clean,
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "GH_TOKEN": "test-token",
            "REPO": REPO,
            "FAKE_GH_STATE": str(self.state_file),
            "FAKE_GH_LOG": str(self.log_file),
            **env,
        }
        return subprocess.run(
            ["bash", str(ROOT / script)], cwd=cwd, env=full, capture_output=True, text=True
        )


@pytest.fixture
def gh(tmp_path: Path) -> FakeGH:
    return FakeGH(tmp_path)


def outputs(result: subprocess.CompletedProcess) -> dict[str, str]:
    out = {}
    for line in result.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.replace("-", "").isalnum():
            out[key] = value
    return out
