"""scripts/semver.sh: SemVer 2.0 precedence."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/semver.sh"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True)


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("1.0.0", "1.0.0", "0"),
        ("1.0.0", "1.0.1", "-1"),
        ("1.10.0", "1.9.0", "1"),
        ("2.0.0", "1.99.99", "1"),
        ("1.0.0-alpha.1", "1.0.0", "-1"),
        ("1.0.0", "1.0.0-rc.9", "1"),
        ("1.0.0-alpha.1", "1.0.0-alpha.2", "-1"),
        ("1.0.0-alpha.10", "1.0.0-alpha.9", "1"),
        ("1.0.0-alpha.5", "1.0.0-alpha04", "-1"),
        ("1.0.0-alpha.1", "1.0.0-beta.1", "-1"),
        ("1.0.0-beta.2", "1.0.0-rc.1", "-1"),
        ("1.0.0-rc.1", "1.0.0-rc.1.1", "-1"),
        ("1.0.0+build.1", "1.0.0+build.2", "0"),
    ],
)
def test_compare(a, b, expected):
    result = _run("compare", a, b)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


@pytest.mark.parametrize("bad", ["1.0", "v1.0.0", "01.0.0", "1.0.0-", "1.0.0-rc.01x!"])
def test_compare_refuses_an_invalid_version(bad):
    result = _run("compare", bad, "1.0.0")
    assert result.returncode == 1
    assert "is not a SemVer version" in result.stderr


@pytest.mark.parametrize(("version", "code"), [("1.2.3", 0), ("1.2.3-rc.1", 0), ("1.2", 1), ("v1.2.3", 1)])
def test_valid(version, code):
    assert _run("valid", version).returncode == code


def test_usage():
    result = _run("frobnicate")
    assert result.returncode == 1
    assert "usage" in result.stderr
