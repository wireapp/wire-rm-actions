"""What the tests share: the fake gh (tests/fake_gh.py) first on PATH, the local HTTP server
the fake endpoints are built on, and the helpers that read a script's outputs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
REPO = "wireapp/example"


GIT_IDENTITY = (("user.email", "test@example.com"), ("user.name", "Test"), ("commit.gpgsign", "false"))


def git(repo: Path, *args: str, **env: str) -> str:
    """``git -C repo args``, its output stripped; a git failure fails the test."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True, env={**os.environ, **env},
    )
    return result.stdout.strip()


def init_repo(path: Path, branch: str = "dev") -> Path:
    """An empty repository on ``branch`` that can commit."""
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", branch)
    for key, value in GIT_IDENTITY:
        git(path, "config", key, value)
    return path


def commit(repo: Path, subject: str, when: str | None = None) -> str:
    """An empty commit, at the ISO 8601 date ``when`` if given; returns its sha."""
    dates = {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when} if when else {}
    git(repo, "commit", "-q", "--allow-empty", "-m", subject, **dates)
    return git(repo, "rev-parse", "HEAD")


def copy_repo(template: Path, dest: Path) -> Path:
    """A copy of a repository built once for the whole module: every git call of a fixture
    costs a process, and a dozen commits cost half a second for each test."""
    shutil.copytree(template, dest, symlinks=True)
    return dest


class QuietHandler(BaseHTTPRequestHandler):
    """A request handler that keeps the test output clean."""

    def log_message(self, *args):
        pass


class LocalServer:
    """An HTTP server on a free port of 127.0.0.1, served from a thread until closed."""

    def __init__(self, handler: type[BaseHTTPRequestHandler]):
        self.server = HTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        # serve_forever looks for a shutdown request every 0.5 s by default, and
        # shutdown() waits for it: half a second added to every test that closes one.
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


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


@pytest.fixture(scope="session")
def curl_without_retries(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A directory whose curl is the real one minus its --retry options.

    A script retries a transient failure (5xx, refused connection, unresolved host) with
    curl's backoff of 1, 2 then 4 seconds: 7 s for each test that provokes one, which is
    not worth it unless the test is about the retries.
    """
    real = shutil.which("curl")
    assert real, "curl is required"
    path = tmp_path_factory.mktemp("curl") / "curl"
    path.write_text(
        "#!/usr/bin/env bash\n"
        "args=()\n"
        "while (($#)); do\n"
        "  case $1 in\n"
        "    --retry) shift 2 ;;\n"
        "    --retry-connrefused) shift ;;\n"
        '    *) args+=("$1"); shift ;;\n'
        "  esac\n"
        "done\n"
        f'exec "{real}" "${{args[@]}}"\n'
    )
    path.chmod(0o755)
    return path.parent


def outputs(result: subprocess.CompletedProcess) -> dict[str, str]:
    out = {}
    for line in result.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.replace("-", "").isalnum():
            out[key] = value
    return out
