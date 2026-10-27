"""scripts/install-crane.sh against a local release archive (file:// base URL)."""

from __future__ import annotations

import hashlib
import io
import os
import platform
import subprocess
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/install-crane.sh"
VERSION = "v0.22.1"
OS = {"Linux": "Linux", "Darwin": "Darwin"}[platform.system()]
ARCH = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "arm64", "arm64": "arm64"}[platform.machine()]
ARCHIVE = f"go-containerregistry_{OS}_{ARCH}.tar.gz"


def _archive(base: Path, members: dict[str, bytes]) -> str:
    """Writes <base>/<VERSION>/<ARCHIVE> holding the members; returns its sha256."""
    (base / VERSION).mkdir(parents=True)
    path = base / VERSION / ARCHIVE
    with tarfile.open(path, "w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(tmp_path: Path, **env: str) -> subprocess.CompletedProcess:
    clean = {k: v for k, v in os.environ.items() if not k.startswith("GITHUB_")}
    # A PATH without any crane, so the script installs.
    bin_dir = tmp_path / "empty-bin"
    bin_dir.mkdir(exist_ok=True)
    full = {
        **clean,
        "PATH": f"{bin_dir}{os.pathsep}/usr/bin:/bin",
        "CRANE_VERSION": VERSION,
        "DEST": str(tmp_path / "dest"),
        "CRANE_BASE_URL": f"file://{tmp_path / 'releases'}",
        **env,
    }
    return subprocess.run(["bash", str(SCRIPT)], env=full, capture_output=True, text=True)


def test_installs_the_binary_of_the_checked_archive(tmp_path: Path):
    sha = _archive(tmp_path / "releases", {"crane": b"#!/bin/sh\necho fake crane\n", "LICENSE": b"x"})
    result = _run(tmp_path, CRANE_SHA256=sha)
    assert result.returncode == 0, result.stderr
    crane = tmp_path / "dest/crane"
    assert crane.read_bytes() == b"#!/bin/sh\necho fake crane\n"
    assert os.access(crane, os.X_OK)
    assert not (tmp_path / "dest/LICENSE").exists()
    assert "installed" in result.stdout


def test_refuses_an_archive_with_another_sha256(tmp_path: Path):
    _archive(tmp_path / "releases", {"crane": b"x"})
    result = _run(tmp_path, CRANE_SHA256="0" * 64)
    assert result.returncode == 1
    assert "::error::" in result.stderr and "sha256" in result.stderr
    assert not (tmp_path / "dest/crane").exists()


def test_refuses_an_archive_without_crane(tmp_path: Path):
    sha = _archive(tmp_path / "releases", {"gcrane": b"x"})
    result = _run(tmp_path, CRANE_SHA256=sha)
    assert result.returncode == 1
    assert "holds no crane binary" in result.stderr
    assert not (tmp_path / "dest/crane").exists()


def test_fails_when_the_archive_is_missing(tmp_path: Path):
    (tmp_path / "releases").mkdir()
    result = _run(tmp_path, CRANE_SHA256="a" * 64)
    assert result.returncode == 1
    assert "could not download" in result.stderr


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"CRANE_VERSION": "0.22.1", "CRANE_SHA256": "a" * 64}, "crane-version must be vX.Y.Z"),
        ({"CRANE_VERSION": VERSION, "CRANE_SHA256": "abc"}, "crane-sha256 must be"),
        ({"CRANE_VERSION": VERSION, "CRANE_SHA256": "a" * 64, "DEST": ""}, "DEST is required"),
    ],
)
def test_refuses_bad_inputs_before_any_download(tmp_path: Path, env: dict[str, str], message: str):
    result = _run(tmp_path, **env)
    assert result.returncode == 1
    assert message in result.stderr


def test_a_crane_already_on_path_is_kept(tmp_path: Path):
    bin_dir = tmp_path / "with-crane"
    bin_dir.mkdir()
    crane = bin_dir / "crane"
    crane.write_text("#!/bin/sh\n")
    crane.chmod(0o755)
    result = _run(tmp_path, PATH=f"{bin_dir}{os.pathsep}/usr/bin:/bin", CRANE_SHA256="not even checked")
    assert result.returncode == 0, result.stderr
    assert "nothing installed" in result.stdout
    assert not (tmp_path / "dest").exists()
