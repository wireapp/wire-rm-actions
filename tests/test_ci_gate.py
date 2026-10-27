"""scripts/ci-gate.sh against the fake gh: the release gate (no release, no tag) and the
checks gate (check runs and legacy statuses of the source commit)."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import REPO, outputs

SCRIPT = "scripts/ci-gate.sh"
SHA = "348ddc047bfdc977b554df64accc40495ee57bcb"
KEYS = (
    "REPO", "VERSION", "TAG_PREFIX", "SOURCE_COMMIT", "RELEASE_GATE", "CHECKS_GATE", "FORCE",
    "CHECKS_FROM", "REQUIRED_CHECKS", "BRANCH", "EXCLUDE_WORKFLOWS", "EXCLUDE_DYNAMIC", "GH_TOKEN",
)
WORKFLOW_REF = f"{REPO}/.github/workflows/prepare-release.yml@refs/heads/dev"


def run_url(rid: int) -> str:
    return f"https://github.com/{REPO}/actions/runs/{rid}/job/{rid}9"


def check(name: str, conclusion: str | None, rid: int | None = 10, started: str = "2026-10-10T10:00:00Z", cid: int = 1):
    return {
        "id": cid,
        "name": name,
        "status": "completed" if conclusion else "in_progress",
        "conclusion": conclusion,
        "started_at": started,
        "details_url": run_url(rid) if rid else "https://ci.example.com/build/1",
    }


@pytest.fixture
def green(gh):
    gh.state["check_runs"] = {SHA: [check("lint", "success"), check("test", "skipped", cid=2)]}
    gh.state["runs"] = {"10": ".github/workflows/qa.yml"}
    return gh


def _run(gh, tmp_path: Path, **env: str):
    base = {"VERSION": "1.41.4", "SOURCE_COMMIT": SHA, "GITHUB_WORKFLOW_REF": WORKFLOW_REF, "GITHUB_RUN_ID": "99"}
    return gh.run(SCRIPT, tmp_path, KEYS, **{**base, **env})


def test_passes(green, tmp_path):
    summary = tmp_path / "summary.md"
    result = _run(green, tmp_path, GITHUB_STEP_SUMMARY=str(summary))
    assert result.returncode == 0, result.stderr
    out = outputs(result)
    assert out["tag"] == "v1.41.4"
    assert out["bypassed"] == "false"
    assert out["checks-inspected"] == "2"
    assert out["status-state"] == "none"
    assert "CI gate passed" in summary.read_text()


def test_existing_release_draft_included(green, tmp_path):
    green.state["releases"] = [{"id": 7, "tag_name": "v1.41.4", "draft": True}]
    result = _run(green, tmp_path)
    assert result.returncode == 1
    assert "already exists for tag v1.41.4 (id(s): 7)" in result.stderr


def test_existing_tag(green, tmp_path):
    green.state["refs"] = [
        {"ref": "refs/tags/v1.41.40", "object": {"type": "commit", "sha": "a" * 40}},
        {"ref": "refs/tags/v1.41.4", "object": {"type": "commit", "sha": "b" * 40}},
    ]
    result = _run(green, tmp_path)
    assert result.returncode == 1
    assert "tag v1.41.4 already exists" in result.stderr


def test_longer_tag_is_not_the_tag(green, tmp_path):
    green.state["refs"] = [{"ref": "refs/tags/v1.41.40", "object": {"type": "commit", "sha": "a" * 40}}]
    assert _run(green, tmp_path).returncode == 0


def test_tag_prefix(green, tmp_path):
    green.state["releases"] = [{"id": 7, "tag_name": "v1.41.4"}]
    result = _run(green, tmp_path, TAG_PREFIX="chart-v")
    assert result.returncode == 0, result.stderr
    assert outputs(result)["tag"] == "chart-v1.41.4"


def test_failed_check(green, tmp_path):
    green.state["check_runs"][SHA].append(check("e2e", "timed_out", cid=3))
    result = _run(green, tmp_path)
    assert result.returncode == 1
    assert "e2e: timed_out" in result.stderr


def test_running_check(green, tmp_path):
    green.state["check_runs"][SHA].append(check("e2e", None, cid=3))
    result = _run(green, tmp_path)
    assert result.returncode == 1
    assert "e2e: in_progress" in result.stderr


def test_latest_outcome_wins(green, tmp_path):
    # A cancelled run superseded by a successful one passes; a success then a failure blocks.
    runs = green.state["check_runs"][SHA]
    runs.append(check("e2e", "cancelled", started="2026-10-10T10:00:00Z", cid=3))
    runs.append(check("e2e", "success", started="2026-10-10T10:02:00Z", cid=4))
    assert _run(green, tmp_path).returncode == 0
    runs.append(check("e2e", "failure", started="2026-10-10T10:05:00Z", cid=5))
    assert _run(green, tmp_path).returncode == 1


def test_own_workflow_and_dynamic_runs_excluded(green, tmp_path):
    green.state["runs"].update(
        {"20": ".github/workflows/prepare-release.yml", "30": "dynamic/dependabot/dependabot-updates"}
    )
    runs = green.state["check_runs"][SHA]
    runs.append(check("Prepare release candidate", "failure", rid=20, cid=3))
    runs.append(check("Dependabot", "failure", rid=30, cid=4))
    runs.append(check("Publish", None, rid=99, cid=5))
    result = _run(green, tmp_path)
    assert result.returncode == 0, result.stderr
    assert outputs(result)["checks-inspected"] == "2"
    assert "Excluding GitHub-managed workflow run 30" in result.stderr
    assert not any("actions/runs/99" in " ".join(c) for c in green.calls())


def test_dynamic_kept_when_asked(green, tmp_path):
    green.state["runs"]["30"] = "dynamic/dependabot/dependabot-updates"
    green.state["check_runs"][SHA].append(check("Dependabot", "failure", rid=30, cid=4))
    assert _run(green, tmp_path, EXCLUDE_DYNAMIC="false").returncode == 1


def test_exclude_workflows(green, tmp_path):
    green.state["runs"]["40"] = ".github/workflows/nightly.yml"
    green.state["check_runs"][SHA].append(check("nightly", "failure", rid=40, cid=3))
    assert _run(green, tmp_path).returncode == 1
    result = _run(green, tmp_path, EXCLUDE_WORKFLOWS=".github/workflows/nightly.yml\nother.yml\n")
    assert result.returncode == 0, result.stderr


def test_non_actions_check_runs_count(green, tmp_path):
    green.state["check_runs"][SHA].append(check("external", "failure", rid=None, cid=3))
    result = _run(green, tmp_path)
    assert result.returncode == 1
    assert "external: failure" in result.stderr


def test_no_check_run_refused(gh, tmp_path):
    result = _run(gh, tmp_path)
    assert result.returncode == 1
    assert "nothing ran" in result.stderr


def test_unreadable_run_fails(green, tmp_path):
    green.state["check_runs"][SHA].append(check("other", "success", rid=50, cid=3))
    result = _run(green, tmp_path)
    assert result.returncode == 1
    assert "actions: read" in result.stderr


@pytest.mark.parametrize("state, ok", [("success", True), ("pending", False), ("error", False)])
def test_legacy_statuses(green, tmp_path, state, ok):
    green.state["statuses"] = {SHA: [{"context": "ci/jenkins", "state": state}]}
    result = _run(green, tmp_path)
    assert (result.returncode == 0) is ok, result.stderr
    if ok:
        assert outputs(result)["status-state"] == "success"


def test_force_bypasses_checks_loudly(gh, tmp_path):
    gh.state["check_runs"] = {SHA: [check("lint", "failure")]}
    summary = tmp_path / "summary.md"
    result = _run(gh, tmp_path, FORCE="true", GITHUB_STEP_SUMMARY=str(summary))
    assert result.returncode == 0, result.stderr
    assert outputs(result)["bypassed"] == "true"
    assert "::warning title=CI gate bypassed::" in result.stdout
    assert "CI gate bypassed" in summary.read_text()
    assert not any("check-runs" in " ".join(c) for c in gh.calls())


def test_force_never_bypasses_the_release_gate(green, tmp_path):
    green.state["releases"] = [{"id": 7, "tag_name": "v1.41.4"}]
    assert _run(green, tmp_path, FORCE="true").returncode == 1


def test_required_list(green, tmp_path):
    runs = green.state["check_runs"][SHA]
    runs.append(check("flaky-optional", "failure", cid=3))
    green.state["statuses"] = {SHA: [{"context": "ci/jenkins", "state": "success"}]}
    result = _run(green, tmp_path, CHECKS_FROM="list", REQUIRED_CHECKS="lint\n  ci/jenkins  \n\nlint\n")
    assert result.returncode == 0, result.stderr
    assert outputs(result)["checks-inspected"] == "2"


@pytest.mark.parametrize(
    "required, message",
    [("missing", "missing: not reported"), ("e2e", "e2e: stale"), ("ci/jenkins", "ci/jenkins: pending"), ("wip", "wip: in_progress")],
)
def test_required_list_fails(green, tmp_path, required, message):
    green.state["check_runs"][SHA] += [check("e2e", "stale", cid=3), check("wip", None, cid=4)]
    green.state["statuses"] = {SHA: [{"context": "ci/jenkins", "state": "pending"}]}
    result = _run(green, tmp_path, CHECKS_FROM="list", REQUIRED_CHECKS=f"lint\n{required}")
    assert result.returncode == 1
    assert message in result.stderr


def test_required_list_empty_refused(green, tmp_path):
    result = _run(green, tmp_path, CHECKS_FROM="list", REQUIRED_CHECKS="\n")
    assert result.returncode == 1
    assert "nothing required" in result.stderr


def test_branch_rules(green, tmp_path):
    green.state["rules"] = {
        "release/1.41": [
            {"type": "deletion"},
            {"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": "lint"}, {"context": "test"}]}},
        ]
    }
    result = _run(green, tmp_path, CHECKS_FROM="branch-rules", BRANCH="release/1.41")
    assert result.returncode == 0, result.stderr
    assert "Required checks (branch-rules): lint, test" in result.stdout
    result = _run(green, tmp_path, CHECKS_FROM="branch-rules", BRANCH="dev")
    assert result.returncode == 1
    assert "nothing required" in result.stderr


def test_checks_gate_only(green, tmp_path):
    green.state["releases"] = [{"id": 7, "tag_name": "v1.41.4"}]
    result = _run(green, tmp_path, RELEASE_GATE="false", VERSION="")
    assert result.returncode == 0, result.stderr
    assert "tag" not in outputs(result)


def test_release_gate_only(gh, tmp_path):
    result = _run(gh, tmp_path, CHECKS_GATE="false", SOURCE_COMMIT="")
    assert result.returncode == 0, result.stderr
    assert not any("check-runs" in " ".join(c) for c in gh.calls())


@pytest.mark.parametrize(
    "env, message",
    [
        ({"VERSION": "1.41"}, "is not a release version"),
        ({"VERSION": "1.41.4\"; x"}, "is not a release version"),
        ({"SOURCE_COMMIT": "abc"}, "is not a full commit sha"),
        ({"FORCE": "yes"}, "force must be true or false"),
        ({"CHECKS_FROM": "some"}, "checks-from must be"),
        ({"CHECKS_FROM": "branch-rules"}, "branch-rules needs a branch"),
        ({"REPO": "nope"}, "is not owner/name"),
        ({"TAG_PREFIX": "v$"}, "tag-prefix"),
    ],
)
def test_invalid_inputs(green, tmp_path, env, message):
    result = _run(green, tmp_path, **env)
    assert result.returncode == 1
    assert message in result.stderr
