"""scripts/release-source.sh: the source branch of a release candidate (verify, against the fake
gh), the commit it is built from (resolve) and the summary of the candidate, in a real git
repository."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from conftest import outputs

SCRIPT = "scripts/release-source.sh"
KEYS = (
    "MODE", "SOURCE_BRANCH", "REPO", "VERSION", "RELEASE_TYPE", "SOURCE_SHA", "BASE_TAG", "FROM_TAG",
    "TAG_PREFIX", "NOTE", "COMMITS",
)
NOTE = "Building the candidate image and packaging the chart. The draft release link appears here once created."


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo: Path, subject: str) -> str:
    _git(repo, "commit", "-q", "--allow-empty", "-m", subject)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """dev at three commits, v1.0.0 on the first; origin/dev at the tip, as a full checkout leaves it."""
    path = tmp_path / "src"
    path.mkdir()
    _git(path, "init", "-q", "-b", "dev")
    for k, v in (("user.email", "test@example.com"), ("user.name", "Test"), ("commit.gpgsign", "false")):
        _git(path, "config", k, v)
    _commit(path, "feat: before the tag")
    _git(path, "tag", "v1.0.0")
    _commit(path, "feat(api): add search")
    _commit(path, "fix: crash on empty team (#42)")
    _git(path, "update-ref", "refs/remotes/origin/dev", "HEAD")
    return path


def _run(gh, cwd: Path, **env: str) -> subprocess.CompletedProcess:
    return gh.run(SCRIPT, cwd, KEYS, **env)


# --- verify -------------------------------------------------------------------------


def test_verify_an_existing_branch(gh, tmp_path):
    gh.state["branches"] = ["dev", "release/1.41"]
    result = _run(gh, tmp_path, MODE="verify", SOURCE_BRANCH="release/1.41")
    assert result.returncode == 0, result.stderr
    assert "Source branch 'release/1.41' exists." in result.stdout.splitlines()
    assert gh.calls() == [["api", "repos/wireapp/example/branches/release/1.41", "--jq", ".name"]]


def test_verify_a_missing_branch_lists_the_release_lines(gh, tmp_path):
    gh.state["branches"] = ["dev", "release/1.40", "feat/x", "release/1.41"]
    summary = tmp_path / "summary.md"
    result = _run(gh, tmp_path, MODE="verify", SOURCE_BRANCH="release/9.9", GITHUB_STEP_SUMMARY=str(summary))
    assert result.returncode == 1
    assert "branch 'release/9.9' does not exist on wireapp/example" in result.stderr
    assert summary.read_text().splitlines() == [
        "### :x: Source branch does not exist",
        "",
        "`release/9.9` does not exist on `wireapp/example`. Release lines that currently exist:",
        "- release/1.40",
        "- release/1.41",
    ]


def test_verify_a_missing_branch_without_any_release_line(gh, tmp_path):
    summary = tmp_path / "summary.md"
    result = _run(gh, tmp_path, MODE="verify", SOURCE_BRANCH="dev", GITHUB_STEP_SUMMARY=str(summary))
    assert result.returncode == 1
    assert summary.read_text().splitlines()[0] == "### :x: Source branch does not exist"
    assert "- " not in summary.read_text()


def test_verify_the_listing_failing_still_fails_the_run(gh, tmp_path):
    gh.state["fail"] = {"GET repos/wireapp/example/branches": "HTTP 500"}
    summary = tmp_path / "summary.md"
    result = _run(gh, tmp_path, MODE="verify", SOURCE_BRANCH="dev", GITHUB_STEP_SUMMARY=str(summary))
    assert result.returncode == 1
    assert "does not exist" in summary.read_text()


@pytest.mark.parametrize("branch", ["", "feat x", "../../orgs", "dev;id", "a..b", "dev$(id)", "é"])
def test_verify_refuses_a_branch_name_before_any_api_call(gh, tmp_path, branch):
    result = _run(gh, tmp_path, MODE="verify", SOURCE_BRANCH=branch)
    assert result.returncode == 1
    assert "source_branch" in result.stderr
    assert gh.calls() == []


@pytest.mark.parametrize("repository", ["example", "wireapp/example/x", "wire app/x", "../x", "./x", "wireapp/..", "wireapp/."])
def test_verify_refuses_a_repository_name(gh, tmp_path, repository):
    result = _run(gh, tmp_path, MODE="verify", SOURCE_BRANCH="dev", REPO=repository)
    assert result.returncode == 1
    assert "is not owner/name" in result.stderr
    assert gh.calls() == []


# --- resolve ------------------------------------------------------------------------


def test_resolve_the_tip_of_the_branch(gh, repo, tmp_path):
    output = tmp_path / "output"
    result = _run(gh, repo, MODE="resolve", SOURCE_BRANCH="dev", GITHUB_OUTPUT=str(output))
    sha = _git(repo, "rev-parse", "HEAD")
    assert result.returncode == 0, result.stderr
    assert f"Resolved source_branch 'dev' to {sha}" in result.stdout
    assert outputs(result) == {"sha": sha}
    assert output.read_text() == f"sha={sha}\n"


def test_resolve_a_release_line(gh, repo):
    _git(repo, "checkout", "-q", "-b", "release/1.41")
    _git(repo, "update-ref", "refs/remotes/origin/release/1.41", "HEAD")
    result = _run(gh, repo, MODE="resolve", SOURCE_BRANCH="release/1.41")
    assert result.returncode == 0, result.stderr
    assert outputs(result)["sha"] == _git(repo, "rev-parse", "HEAD")


def test_resolve_refuses_a_checkout_behind_the_tip(gh, repo):
    tip = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "HEAD~1")
    result = _run(gh, repo, MODE="resolve", SOURCE_BRANCH="dev")
    assert result.returncode == 1
    assert "not at the tip of origin/dev" in result.stderr
    assert tip in result.stderr
    assert outputs(result) == {}


def test_resolve_refuses_a_branch_that_was_not_fetched(gh, repo):
    result = _run(gh, repo, MODE="resolve", SOURCE_BRANCH="release/1.41")
    assert result.returncode == 1
    assert "branch 'release/1.41' is not in the checkout" in result.stderr


def test_resolve_refuses_a_bad_branch_name(gh, repo):
    result = _run(gh, repo, MODE="resolve", SOURCE_BRANCH="dev;id")
    assert result.returncode == 1
    assert "is not a branch name" in result.stderr


# --- summary ------------------------------------------------------------------------


@pytest.fixture
def summary_env(repo: Path) -> dict[str, str]:
    return {
        "MODE": "summary", "SOURCE_BRANCH": "dev", "VERSION": "1.1.0-rc.1", "RELEASE_TYPE": "rc",
        "SOURCE_SHA": _git(repo, "rev-parse", "HEAD"), "BASE_TAG": "v1.0.0", "FROM_TAG": "v1.0.0",
    }


def _summary(gh, repo: Path, tmp_path: Path, env: dict[str, str], **more: str):
    path = tmp_path / "summary.md"
    path.write_text("")
    result = _run(gh, repo, **{**env, **more, "GITHUB_STEP_SUMMARY": str(path)})
    return result, path.read_text()


def test_summary_of_the_candidate(gh, repo, tmp_path, summary_env):
    sha = summary_env["SOURCE_SHA"]
    short = sha[:7]
    result, text = _summary(gh, repo, tmp_path, summary_env, NOTE=NOTE)
    assert result.returncode == 0, result.stderr
    assert outputs(result) == {"commit-count": "2"}
    assert text == f"""\
## Preparing `v1.1.0-rc.1`

| | |
| --- | --- |
| Version | `1.1.0-rc.1` |
| Channel | `rc` |
| Source branch | `dev` |
| Source commit | `{sha}` |
| Anchor (latest release reachable) | `v1.0.0` |
| Changes since | `v1.0.0` |

<details>
<summary>Commits since v1.0.0</summary>

- {short} fix: crash on empty team (#42)
- {_git(repo, "rev-parse", "--short", "HEAD~1")} feat(api): add search

</details>

{NOTE}
"""


def test_summary_without_commits_since_the_tag(gh, repo, tmp_path, summary_env):
    _git(repo, "tag", "v1.0.1")
    result, text = _summary(gh, repo, tmp_path, summary_env, FROM_TAG="v1.0.1", BASE_TAG="v1.0.1")
    assert result.returncode == 0, result.stderr
    assert outputs(result) == {"commit-count": "0"}
    assert "<summary>Commits since v1.0.1</summary>\n\n_No commits since v1.0.1._\n\n</details>\n" in text
    assert text.endswith("</details>\n")


def test_summary_without_the_commit_list(gh, repo, tmp_path, summary_env):
    result, text = _summary(gh, repo, tmp_path, summary_env, COMMITS="false")
    assert result.returncode == 0, result.stderr
    assert outputs(result) == {"commit-count": "2"}
    assert "<details>" not in text
    assert text.endswith("| Changes since | `v1.0.0` |\n")


def test_summary_with_another_tag_prefix(gh, repo, tmp_path, summary_env):
    result, text = _summary(gh, repo, tmp_path, summary_env, TAG_PREFIX="example-")
    assert result.returncode == 0, result.stderr
    assert text.startswith("## Preparing `example-1.1.0-rc.1`\n")


def test_summary_without_a_job_summary_still_outputs_the_count(gh, repo, summary_env):
    result = _run(gh, repo, **summary_env)
    assert result.returncode == 0, result.stderr
    assert outputs(result) == {"commit-count": "2"}


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"SOURCE_BRANCH": ""}, "source_branch is required"),
        ({"VERSION": ""}, "version is required"),
        ({"RELEASE_TYPE": ""}, "release_type is required"),
        ({"SOURCE_SHA": "abc123"}, "source_sha 'abc123' is not a full sha"),
        ({"SOURCE_SHA": "0" * 39 + "G"}, "is not a full sha"),
        ({"BASE_TAG": ""}, "base_tag is required"),
        ({"FROM_TAG": ""}, "from_tag '' is not a tag name"),
        ({"FROM_TAG": "--all"}, "from_tag '--all' is not a tag name"),
        ({"FROM_TAG": "v1 0"}, "is not a tag name"),
        ({"TAG_PREFIX": "v;"}, "is not a tag prefix"),
        ({"COMMITS": "yes"}, "commits must be true or false"),
    ],
)
def test_summary_refuses(gh, repo, tmp_path, summary_env, change, message):
    result, text = _summary(gh, repo, tmp_path, summary_env, **change)
    assert result.returncode == 1
    assert message in result.stderr
    assert text == ""
    assert outputs(result) == {}


def test_summary_refuses_an_unknown_tag(gh, repo, tmp_path, summary_env):
    result, text = _summary(gh, repo, tmp_path, summary_env, FROM_TAG="v9.9.9")
    assert result.returncode != 0
    assert text == ""


def test_an_unknown_mode_is_refused(gh, tmp_path):
    result = _run(gh, tmp_path, MODE="publish")
    assert result.returncode == 1
    assert "MODE must be verify, resolve or summary" in result.stderr
