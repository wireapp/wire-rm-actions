"""scripts/wire-builds-bump.sh against the fake gh: the chart entry and the build version in
one commit, a no-op when already there, retried when another commit lands in between."""

from __future__ import annotations

import json

import pytest
from conftest import outputs

SCRIPT = "scripts/wire-builds-bump.sh"
KEYS = (
    "CHART", "VERSION", "CHART_REPO", "APP_VERSION", "COMMIT", "COMMIT_URL", "SOURCE_REPOSITORY",
    "WIRE_BUILDS_REPOSITORY", "BRANCH", "FILE", "MESSAGE", "BUMP_BUILD_VERSION", "ATTEMPTS", "RETRY_DELAY",
)
SHA = "5d202dc2abc5d98028027309e50661c7a359c7c8"
S3 = "https://s3-eu-west-1.amazonaws.com/public.wire.com/charts-webapp"
BUILD = {
    "helmCharts": {
        "wire-server": {"repo": "https://example.com/charts-develop", "version": "5.38.13", "meta": {"commit": "a" * 40}},
        "team-settings": {
            "repo": S3,
            "version": "4.24.4-alpha.6",
            "meta": {"appVersion": "4.24.4-alpha.6", "commitURL": "https://x/commit/b", "commit": "b" * 40, "keep": "me"},
        },
    },
    "version": "1.0.0-zulu.5897",
}


def _text(build: dict) -> str:
    # The layout of wire-builds: jq's default output.
    return json.dumps(build, indent=2) + "\n"


@pytest.fixture
def wb(gh):
    gh.state["repo"] = "wireapp/wire-builds"
    gh.state["contents"] = {"dev:build.json": _text(BUILD)}
    return gh


def _run(gh, tmp_path, **env):
    base = {"CHART": "team-settings", "VERSION": "4.24.4", "COMMIT": SHA, "SOURCE_REPOSITORY": "wireapp/wire-team-settings", "RETRY_DELAY": "0"}
    return gh.run(SCRIPT, tmp_path, KEYS, **{**base, **env})


def _build(gh) -> dict:
    return json.loads(gh.load()["contents"]["dev:build.json"])


def test_bump(wb, tmp_path):
    result = _run(wb, tmp_path)
    assert result.returncode == 0, result.stderr
    out = outputs(result)
    assert out["status"] == "bumped"
    assert out["build-version"] == "1.0.0-zulu.5898"
    assert out["commit"] == f"{1:040x}"
    build = _build(wb)
    assert build["version"] == "1.0.0-zulu.5898"
    assert build["helmCharts"]["team-settings"] == {
        "repo": S3,
        "version": "4.24.4",
        "meta": {
            "appVersion": "4.24.4",
            "commitURL": f"https://github.com/wireapp/wire-team-settings/commit/{SHA}",
            "commit": SHA,
            "keep": "me",
        },
    }
    assert build["helmCharts"]["wire-server"] == BUILD["helmCharts"]["wire-server"]
    assert wb.state["commits"] == ["Bump team-settings to 4.24.4"]
    # The layout is kept: a diff of wire-builds shows the changed lines only.
    assert wb.state["contents"]["dev:build.json"].startswith('{\n  "helmCharts": {\n')


def test_rerun_is_a_no_op(wb, tmp_path):
    assert _run(wb, tmp_path).returncode == 0
    wb.load()
    calls = len(wb.calls())
    result = _run(wb, tmp_path)
    assert result.returncode == 0, result.stderr
    out = outputs(result)
    assert out["status"] == "unchanged"
    assert out["build-version"] == "1.0.0-zulu.5898"
    assert out["commit"] == ""
    assert wb.load()["commits"] == ["Bump team-settings to 4.24.4"]
    assert not any("PUT" in c for c in wb.calls()[calls:])


def test_another_commit_lands_in_between(wb, tmp_path):
    other = json.loads(json.dumps(BUILD))
    other["version"] = "1.0.0-zulu.5900"
    other["helmCharts"]["wire-server"]["version"] = "5.38.14"
    wb.state["contents_race"] = [_text(other)]
    result = _run(wb, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "attempt 1/5" in result.stdout
    build = _build(wb)
    assert build["version"] == "1.0.0-zulu.5901"
    assert build["helmCharts"]["wire-server"]["version"] == "5.38.14"
    assert build["helmCharts"]["team-settings"]["version"] == "4.24.4"


def test_gives_up_after_the_attempts(wb, tmp_path):
    wb.state["contents_race"] = [_text({**BUILD, "version": f"1.0.0-zulu.{n}"}) for n in range(6000, 6003)]
    result = _run(wb, tmp_path, ATTEMPTS="2")
    assert result.returncode == 1
    assert "after 2 attempt(s)" in result.stderr


def test_a_landed_commit_is_seen_on_the_retry(wb, tmp_path):
    landed = json.loads(json.dumps(BUILD))
    landed["version"] = "1.0.0-zulu.5898"
    landed["helmCharts"]["team-settings"] = {
        "repo": S3, "version": "4.24.4",
        "meta": {"appVersion": "4.24.4", "commit": SHA, "commitURL": f"https://github.com/wireapp/wire-team-settings/commit/{SHA}"},
    }
    wb.state["contents_race"] = [_text(landed)]
    result = _run(wb, tmp_path)
    assert result.returncode == 0, result.stderr
    assert outputs(result)["status"] == "unchanged"
    assert _build(wb)["version"] == "1.0.0-zulu.5898"


def test_new_entry_needs_the_repo(wb, tmp_path):
    result = _run(wb, tmp_path, CHART="sftd", VERSION="5.6.0")
    assert result.returncode == 1
    assert "CHART_REPO is required" in result.stderr
    result = _run(wb, tmp_path, CHART="sftd", VERSION="5.6.0", CHART_REPO="https://example.com/charts", APP_VERSION="-", COMMIT="")
    assert result.returncode == 0, result.stderr
    assert _build(wb)["helmCharts"]["sftd"] == {"version": "5.6.0", "repo": "https://example.com/charts", "meta": {}}


def test_options(wb, tmp_path):
    result = _run(
        wb, tmp_path, BUMP_BUILD_VERSION="false", MESSAGE="team-settings 4.24.4 (GA)",
        APP_VERSION="4.24.4-custom", COMMIT_URL="https://example.com/c", BRANCH="dev",
    )
    assert result.returncode == 0, result.stderr
    build = _build(wb)
    assert build["version"] == "1.0.0-zulu.5897"
    assert build["helmCharts"]["team-settings"]["meta"]["appVersion"] == "4.24.4-custom"
    assert build["helmCharts"]["team-settings"]["meta"]["commitURL"] == "https://example.com/c"
    assert wb.state["commits"] == ["team-settings 4.24.4 (GA)"]


@pytest.mark.parametrize(
    "version, message",
    [("1.0.0", "has no pre-release to bump"), ("1.0.0-zulu", "does not end with a number")],
)
def test_build_version_must_be_bumpable(wb, tmp_path, version, message):
    wb.state["contents"]["dev:build.json"] = _text({**BUILD, "version": version})
    result = _run(wb, tmp_path)
    assert result.returncode == 1
    assert message in result.stderr
    assert "commits" not in wb.load()


@pytest.mark.parametrize(
    "env, message",
    [
        ({"CHART": "a b"}, "is not a chart name"),
        ({"VERSION": "v4.24.4"}, "is not a SemVer version"),
        ({"COMMIT": "abc"}, "is not a full commit sha"),
        ({"CHART_REPO": "http://plain"}, "is not an https:// or oci:// URL"),
        ({"FILE": "../build.json"}, "is not a plain path"),
        ({"BUMP_BUILD_VERSION": "yes"}, "must be true or false"),
        ({"ATTEMPTS": "0"}, "must be a positive number"),
        ({"COMMIT_URL": "", "SOURCE_REPOSITORY": ""}, "COMMIT_URL or SOURCE_REPOSITORY is required"),
    ],
)
def test_invalid_inputs(wb, tmp_path, env, message):
    result = _run(wb, tmp_path, **env)
    assert result.returncode == 1
    assert message in result.stderr
    assert wb.calls() == []


def test_missing_file(wb, tmp_path):
    result = _run(wb, tmp_path, BRANCH="main")
    assert result.returncode == 1
    assert "could not read build.json of wireapp/wire-builds@main" in result.stderr
