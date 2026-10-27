"""scripts/release-version.sh: the next release version of a branch."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/release-version.sh"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def _commit(repo: Path, msg: str) -> str:
    (repo / "a").write_text(msg)
    _git(repo, "add", "a")
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


def _remote_branch(repo: Path, branch: str) -> None:
    """Make HEAD visible as origin/<branch>, as a fetch-depth 0 checkout would."""
    _git(repo, "update-ref", f"refs/remotes/origin/{branch}", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "-C", str(path), "init", "-q", "-b", "dev"], check=True)
    for k, v in (("user.email", "test@example.com"), ("user.name", "Test"), ("commit.gpgsign", "false")):
        _git(path, "config", k, v)
    _commit(path, "first")
    _git(path, "tag", "v1.41.4")
    _commit(path, "next")
    _remote_branch(path, "dev")
    return path


def _run(repo: Path, **env: str) -> subprocess.CompletedProcess:
    clean = {k: v for k, v in os.environ.items() if not k.startswith("GITHUB_")}
    output = repo.parent / "github-output"
    output.write_text("")
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=repo,
        env={**clean, "GITHUB_OUTPUT": str(output), "SOURCE_BRANCH": "dev", "RELEASE_TYPE": "ga", **env},
        capture_output=True,
        text=True,
    )


def _ok(repo: Path, **env: str) -> dict[str, str]:
    result = _run(repo, **env)
    assert result.returncode == 0, result.stderr
    lines = (repo.parent / "github-output").read_text().splitlines()
    return dict(line.split("=", 1) for line in lines)


def test_ga_after_ga_bumps_patch(repo):
    out = _ok(repo)
    assert out["version"] == "1.41.5"
    assert out["kind"] == "ga"
    assert out["tag"] == "v1.41.5"
    assert out["latest-tag"] == "v1.41.4"
    assert out["from-tag"] == "v1.41.4"
    assert out["sha"] == _git(repo, "rev-parse", "HEAD")


@pytest.mark.parametrize(("bump", "version"), [("minor", "1.42.0"), ("major", "2.0.0")])
def test_ga_after_ga_honours_the_bump(repo, bump, version):
    assert _ok(repo, VERSION_BUMP=bump)["version"] == version


def test_first_prerelease_after_ga(repo):
    out = _ok(repo, RELEASE_TYPE="rc", VERSION_BUMP="minor")
    assert out["version"] == "1.42.0-rc.1"
    assert out["kind"] == "prerelease"
    assert out["from-tag"] == "v1.41.4"


def test_same_channel_increments(repo):
    _git(repo, "tag", "v1.42.0-rc.1")
    _commit(repo, "fix")
    _remote_branch(repo, "dev")
    out = _ok(repo, RELEASE_TYPE="rc")
    assert out["version"] == "1.42.0-rc.2"
    assert out["from-tag"] == "v1.42.0-rc.1"


def test_higher_channel_restarts_at_one(repo):
    _git(repo, "tag", "v1.42.0-beta.3")
    _commit(repo, "fix")
    _remote_branch(repo, "dev")
    out = _ok(repo, RELEASE_TYPE="rc")
    assert out["version"] == "1.42.0-rc.1"
    assert out["from-tag"] == "v1.41.4"


def test_lower_channel_is_refused(repo):
    _git(repo, "tag", "v1.42.0-rc.1")
    result = _run(repo, RELEASE_TYPE="beta")
    assert result.returncode == 1
    assert "never moves backward in channel maturity" in result.stderr


def test_ga_promotes_a_prerelease(repo):
    _git(repo, "tag", "v1.42.0-rc.2")
    out = _ok(repo)
    assert out["version"] == "1.42.0"
    assert out["from-tag"] == "v1.41.4"


@pytest.mark.parametrize(
    ("release_type", "bump", "version"),
    [("alpha", "minor", "1.43.0-alpha.1"), ("rc", "major", "2.0.0-rc.1"), ("ga", "minor", "1.43.0"), ("ga", "major", "2.0.0")],
)
def test_explicit_bump_from_a_prerelease_opens_a_new_line(repo, release_type, bump, version):
    _git(repo, "tag", "v1.42.0-rc.2")
    result = _run(repo, RELEASE_TYPE=release_type, VERSION_BUMP=bump)
    assert result.returncode == 0, result.stderr
    assert "opens a new line" in result.stdout
    out = dict(line.split("=", 1) for line in (repo.parent / "github-output").read_text().splitlines())
    assert out["version"] == version
    assert out["latest-tag"] == "v1.42.0-rc.2"
    assert out["from-tag"] == "v1.41.4"


def test_explicit_bump_from_a_prerelease_ignores_the_channel_order(repo):
    _git(repo, "tag", "v1.42.0-rc.2")
    assert _ok(repo, RELEASE_TYPE="alpha", VERSION_BUMP="minor")["version"] == "1.43.0-alpha.1"


def test_release_line_refuses_a_new_line_from_a_prerelease(repo):
    _git(repo, "tag", "v1.41.5-alpha.1")
    _remote_branch(repo, "release/1.41")
    result = _run(repo, SOURCE_BRANCH="release/1.41", RELEASE_TYPE="alpha", VERSION_BUMP="minor")
    assert result.returncode == 1
    assert "may only produce 1.41.* releases" in result.stderr


def test_several_tags_on_the_anchor_commit_take_the_highest(repo):
    _git(repo, "tag", "v1.42.0-alpha.5")
    _git(repo, "tag", "v1.42.0-alpha.6")
    _commit(repo, "fix")
    _remote_branch(repo, "dev")
    out = _ok(repo, RELEASE_TYPE="alpha")
    assert out["version"] == "1.42.0-alpha.7"
    assert out["latest-tag"] == "v1.42.0-alpha.6"
    _git(repo, "tag", "v1.42.0", "HEAD~1")
    assert _ok(repo)["version"] == "1.42.1"


def test_legacy_prerelease_form_is_not_continued(repo):
    _git(repo, "tag", "v1.42.0-rc04")
    result = _run(repo, RELEASE_TYPE="rc")
    assert result.returncode == 1
    assert "former pre-release form" in result.stderr
    assert _ok(repo)["version"] == "1.42.0"


def test_release_line_stays_in_its_line(repo):
    _git(repo, "branch", "release/1.41")
    _remote_branch(repo, "release/1.41")
    assert _ok(repo, SOURCE_BRANCH="release/1.41")["version"] == "1.41.5"
    result = _run(repo, SOURCE_BRANCH="release/1.41", VERSION_BUMP="minor")
    assert result.returncode == 1
    assert "may only produce 1.41.* releases" in result.stderr


def test_release_line_ignores_newer_minors(repo):
    _remote_branch(repo, "release/1.41")
    _git(repo, "checkout", "-q", "-b", "trunk", "HEAD~1")
    _commit(repo, "a newer minor elsewhere")
    _git(repo, "tag", "v1.42.0")
    assert _ok(repo, SOURCE_BRANCH="release/1.41")["version"] == "1.41.5"


def test_trunk_candidate_must_be_the_newest_release(repo):
    _git(repo, "tag", "v1.42.0")
    _git(repo, "checkout", "-q", "-b", "other", "HEAD~1")
    _commit(repo, "elsewhere")
    _git(repo, "update-ref", "refs/remotes/origin/dev", "HEAD")
    result = _run(repo, VERSION_BUMP="patch")
    assert result.returncode == 1
    assert "is already ahead of the computed target" in result.stderr


def test_existing_tag_is_refused(repo):
    _git(repo, "tag", "v1.41.5")
    _commit(repo, "more")
    _remote_branch(repo, "dev")
    _git(repo, "tag", "-d", "v1.41.5")
    _git(repo, "tag", "v1.41.5", "HEAD~1")
    _git(repo, "update-ref", "refs/remotes/origin/dev", "HEAD~2")
    result = _run(repo)
    assert result.returncode == 1
    assert "already exists" in result.stderr


def test_expected_version_must_match(repo):
    result = _run(repo, EXPECTED_VERSION="1.42.0")
    assert result.returncode == 1
    assert "differs from expected_version '1.42.0'" in result.stderr
    assert _ok(repo, EXPECTED_VERSION="1.41.5")["version"] == "1.41.5"


def test_tag_prefix(repo):
    _git(repo, "tag", "2.0.0")
    out = _ok(repo, TAG_PREFIX="")
    assert out["version"] == "2.0.1"
    assert out["tag"] == "2.0.1"


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"SOURCE_BRANCH": ""}, "SOURCE_BRANCH is required"),
        ({"SOURCE_BRANCH": "nope"}, "is not available as origin/nope"),
        ({"RELEASE_TYPE": "stable"}, "RELEASE_TYPE must be one of ga, alpha, beta, rc"),
        ({"VERSION_BUMP": "huge"}, "VERSION_BUMP must be one of patch, minor, major"),
    ],
)
def test_refused_inputs(repo, env, message):
    result = _run(repo, **env)
    assert result.returncode == 1
    assert message in result.stderr


def test_no_release_tag_fails(tmp_path):
    repo = tmp_path / "bare"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "dev"], check=True)
    for k, v in (("user.email", "test@example.com"), ("user.name", "Test"), ("commit.gpgsign", "false")):
        _git(repo, "config", k, v)
    _commit(repo, "first")
    _remote_branch(repo, "dev")
    result = _run(repo)
    assert result.returncode == 1
    assert "no release tag v* is reachable" in result.stderr
