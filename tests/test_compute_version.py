"""The ADR-0018 version computed by scripts/compute-version.sh."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/compute-version.sh"
TS = "20260930120000"
DATE = "2026-09-30T14:00:00+02:00"


def init_repo(path: Path, branch: str) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-q", "-b", branch], check=True)
    for k, v in (("user.email", "test@example.com"), ("user.name", "Test"), ("commit.gpgsign", "false")):
        subprocess.run(["git", "-C", str(path), "config", k, v], check=True)
    return path


def commit_file(repo: Path, rel_path: str, content: str, date_iso: str, msg: str) -> None:
    (repo / rel_path).write_text(content)
    subprocess.run(["git", "-C", str(repo), "add", rel_path], check=True)
    env = {**os.environ, "GIT_AUTHOR_DATE": date_iso, "GIT_COMMITTER_DATE": date_iso}
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", msg], check=True, env=env)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _run(repo: Path, **env: str) -> subprocess.CompletedProcess:
    clean = {k: v for k, v in os.environ.items() if k != "GITHUB_OUTPUT"}
    return subprocess.run(
        ["bash", str(SCRIPT)], cwd=repo, env={**clean, **env}, capture_output=True, text=True
    )


def _version(repo: Path, **env: str) -> dict[str, str]:
    result = _run(repo, **env)
    assert result.returncode == 0, result.stderr
    return dict(line.split("=", 1) for line in result.stdout.splitlines())


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = init_repo(tmp_path / "src", branch="dev")
    commit_file(path, "a", "1", "2026-09-01T10:00:00+00:00", "first")
    return path


def _sha7(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD")[:7]


def test_dev_build_after_ga_bumps_patch(repo: Path):
    _git(repo, "tag", "v5.2.0")
    commit_file(repo, "a", "2", DATE, "next")
    out = _version(repo, BRANCH="dev")
    assert out["version"] == f"5.2.1-{TS}.g{_sha7(repo)}"
    assert out["kind"] == "dev"
    assert out["base_tag"] == "v5.2.0"
    assert out["branch_kind"] == "release"


def test_feature_branch_carries_branch_identifier(repo: Path):
    _git(repo, "tag", "v5.2.0")
    commit_file(repo, "a", "2", DATE, "next")
    out = _version(repo, BRANCH="feat/Login_Fix")
    assert out["version"] == f"5.2.1-{TS}.login-fix.g{_sha7(repo)}"
    assert out["branch_kind"] == "feature"


def test_branch_identifier_is_cut_to_fourteen(repo: Path):
    _git(repo, "tag", "v1.0.0")
    out = _version(repo, BRANCH="fix/a-very-long-branch-name")
    assert f".a-very-long-br.g{_sha7(repo)}" in out["version"]


def test_branch_identifier_drops_trailing_dashes(repo: Path):
    _git(repo, "tag", "v1.0.0")
    out = _version(repo, BRANCH="feature/wpb-28906-factorize-gha")
    assert f".wpb-28906-fact.g{_sha7(repo)}" in out["version"]
    out = _version(repo, BRANCH="feature/WPB-123_login__fix")
    assert f".wpb-123-login.g{_sha7(repo)}" in out["version"]


def test_dev_build_after_prerelease_appends(repo: Path):
    _git(repo, "tag", "v5.3.0-rc.2")
    commit_file(repo, "a", "2", DATE, "next")
    assert _version(repo, BRANCH="dev")["version"] == f"5.3.0-rc.2.{TS}.g{_sha7(repo)}"


def test_ga_wins_over_prerelease_on_same_commit(repo: Path):
    _git(repo, "tag", "v5.3.0-rc.2")
    _git(repo, "tag", "v5.3.0")
    commit_file(repo, "a", "2", DATE, "next")
    assert _version(repo, BRANCH="dev")["version"].startswith("5.3.1-")


def test_other_tags_are_skipped(repo: Path):
    _git(repo, "tag", "v4.0.0")
    commit_file(repo, "a", "2", DATE, "next")
    _git(repo, "tag", "v4.1.0-pre.3")
    _git(repo, "tag", "chart-1.2.3")
    assert _version(repo, BRANCH="dev")["version"].startswith("4.0.1-")


def test_tag_build_is_the_tag(repo: Path):
    _git(repo, "tag", "v5.3.0-beta.1")
    out = _version(repo, TAG="v5.3.0-beta.1")
    assert out["version"] == "5.3.0-beta.1"
    assert out["kind"] == "prerelease"


@pytest.mark.parametrize("tag", ["v5.3.0-pre.1", "v5.3", "v5.3.0-rc.0", "5.3.0"])
def test_tag_build_refuses_other_forms(repo: Path, tag: str):
    _git(repo, "tag", tag)
    assert _run(repo, TAG=tag).returncode != 0


def test_no_reachable_tag_fails(repo: Path):
    result = _run(repo, BRANCH="dev")
    assert result.returncode != 0
    assert "no GA or pre-release tag" in result.stderr


def test_leading_zero_numeric_branch_fails(repo: Path):
    _git(repo, "tag", "v1.0.0")
    assert _run(repo, BRANCH="feat/0123").returncode != 0


def test_release_branches_are_configurable(repo: Path):
    _git(repo, "tag", "v1.0.0")
    out = _version(repo, BRANCH="develop", RELEASE_BRANCHES="^dev$")
    assert out["branch_kind"] == "feature"
    assert ".develop.g" in out["version"]
