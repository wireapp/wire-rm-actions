"""scripts/release-inputs.sh: the dispatch inputs of a prepare-release workflow."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/release-inputs.sh"
REQUEST = "0f8fad5b-d9cb-4b1c-a7a2-1f0d4e8e6a3b"
BASE = {"SOURCE_BRANCH": "dev", "RELEASE_TYPE": "rc", "VERSION_BUMP": "patch"}


def _run(tmp_path: Path, **env: str) -> tuple[subprocess.CompletedProcess, dict[str, str]]:
    output = tmp_path / "github-output"
    output.touch()
    clean = {k: v for k, v in os.environ.items() if not k.startswith("GITHUB_")}
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env={**clean, "GITHUB_OUTPUT": str(output), **BASE, **env},
        capture_output=True,
        text=True,
    )
    lines = output.read_text().splitlines()
    return result, dict(line.split("=", 1) for line in lines)


def test_manual_run(tmp_path):
    result, out = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert out == {"rm-driven": "false", "force": "false", "release-type": "rc"}
    assert "rm-driven=false" in result.stdout.splitlines()


def test_release_manager_run(tmp_path):
    result, out = _run(tmp_path, REQUEST_ID=REQUEST, RM_ORIGIN="staging", FORCE="true", EXPECTED_VERSION="1.2.0-rc.1")
    assert result.returncode == 0, result.stderr
    assert out == {"rm-driven": "true", "force": "true", "release-type": "rc"}
    assert "::warning" not in result.stderr


def test_local_release_manager_warns(tmp_path):
    result, out = _run(tmp_path, REQUEST_ID=REQUEST, RM_ORIGIN="local")
    assert result.returncode == 0, result.stderr
    assert "::warning title=rm_origin local::" in result.stderr
    assert out["rm-driven"] == "true"


def test_release_line_and_declaration(tmp_path):
    declaration = json.dumps({"schema": "v1alpha2", "changes": []})
    result, out = _run(tmp_path, SOURCE_BRANCH="release/1.41", RELEASE_TYPE="ga", RELEASE_DECLARATION=declaration)
    assert result.returncode == 0, result.stderr
    assert out["release-type"] == "ga"


def test_custom_source_branches(tmp_path):
    result, _ = _run(tmp_path, SOURCE_BRANCH="main", SOURCE_BRANCHES="^main$")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"SOURCE_BRANCH": ""}, "source_branch is required"),
        ({"SOURCE_BRANCH": "feat/x"}, "is not a releasable branch"),
        ({"SOURCE_BRANCH": "release/1"}, "is not a releasable branch"),
        ({"RELEASE_TYPE": "stable"}, "type must be one of ga, alpha, beta, rc"),
        ({"VERSION_BUMP": "huge"}, "version_bump must be one of patch, minor, major"),
        ({"FORCE": "yes"}, "force must be true or false"),
        ({"REQUEST_ID": "not-a-uuid", "RM_ORIGIN": "staging"}, "is not a lower-case UUID4"),
        ({"REQUEST_ID": REQUEST.upper(), "RM_ORIGIN": "staging"}, "is not a lower-case UUID4"),
        ({"EXPECTED_VERSION": "v1.2.3"}, "expected_version 'v1.2.3' is not X.Y.Z"),
        ({"EXPECTED_VERSION": "1.2.3-rc1"}, "is not X.Y.Z"),
        ({"REQUEST_ID": REQUEST}, "rm_origin is required when request_id is set"),
        ({"RM_ORIGIN": "staging"}, "is set without a request_id"),
        ({"REQUEST_ID": REQUEST, "RM_ORIGIN": "dev"}, "rm_origin must be staging, prod or local"),
        ({"RELEASE_DECLARATION": "[]"}, "release_declaration is not the JSON text of an object"),
        ({"RELEASE_DECLARATION": "{not json"}, "release_declaration is not the JSON text of an object"),
        ({"RELEASE_NOTE": "é" * 60000}, "above the 60000 budget"),
    ],
)
def test_refused_inputs(tmp_path, env, message):
    result, out = _run(tmp_path, **env)
    assert result.returncode == 1
    assert message in result.stderr
    assert out == {}


def test_budget_counts_characters_not_bytes(tmp_path):
    result, _ = _run(tmp_path, RELEASE_NOTE="é" * 59000)
    assert result.returncode == 0, result.stderr


# --- publish ------------------------------------------------------------------------


def _publish(tmp_path: Path, **env: str) -> tuple[subprocess.CompletedProcess, dict[str, str]]:
    output = tmp_path / "github-output"
    output.touch()
    clean = {k: v for k, v in os.environ.items() if not k.startswith("GITHUB_")}
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env={**clean, "GITHUB_OUTPUT": str(output), "MODE": "publish", "VERSION": "1.41.4", **env},
        capture_output=True,
        text=True,
    )
    lines = output.read_text().splitlines()
    return result, dict(line.split("=", 1) for line in lines)


def test_publish_manual_run(tmp_path):
    result, out = _publish(tmp_path)
    assert result.returncode == 0, result.stderr
    assert out == {"rm-driven": "false", "release-type": "ga"}
    assert "Inputs validated for v1.41.4." in result.stdout


def test_publish_release_manager_run(tmp_path):
    result, out = _publish(
        tmp_path, VERSION="1.42.0-rc.3", RELEASE_ID="123456", REQUEST_ID=REQUEST, RM_ORIGIN="prod"
    )
    assert result.returncode == 0, result.stderr
    assert out == {"rm-driven": "true", "release-type": "rc"}
    assert "::warning" not in result.stderr


@pytest.mark.parametrize("stage", ["alpha", "beta", "rc"])
def test_publish_release_type_is_the_channel_of_the_version(tmp_path, stage):
    _, out = _publish(tmp_path, VERSION=f"2.0.0-{stage}.10")
    assert out["release-type"] == stage


def test_publish_local_release_manager_warns(tmp_path):
    result, out = _publish(tmp_path, REQUEST_ID=REQUEST, RM_ORIGIN="local")
    assert result.returncode == 0, result.stderr
    assert "::warning title=rm_origin local::request " + REQUEST in result.stderr
    assert out["rm-driven"] == "true"


def test_publish_needs_none_of_the_prepare_inputs(tmp_path):
    result, out = _publish(tmp_path, SOURCE_BRANCH="feat/x", RELEASE_TYPE="stable", FORCE="yes")
    assert result.returncode == 0, result.stderr
    assert "force" not in out


def test_publish_has_no_size_budget(tmp_path):
    # Above the 60 000 budget, below the 128 KiB Linux limit on a single env var (2 bytes each).
    result, _ = _publish(tmp_path, RELEASE_NOTE="é" * 62000)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"VERSION": ""}, "version '' is not a release version"),
        ({"VERSION": "v1.41.4"}, "version 'v1.41.4' is not a release version"),
        ({"VERSION": "1.41"}, "is not a release version"),
        ({"VERSION": "1.41.4-rc1"}, "is not a release version"),
        ({"VERSION": "1.41.4-snapshot.1"}, "is not a release version"),
        ({"RELEASE_ID": "12a"}, "release_id '12a' is not numeric"),
        ({"RELEASE_ID": "../x"}, "is not numeric"),
        ({"REQUEST_ID": "not-a-uuid", "RM_ORIGIN": "staging"}, "is not a lower-case UUID4"),
        ({"REQUEST_ID": REQUEST.upper(), "RM_ORIGIN": "staging"}, "is not a lower-case UUID4"),
        ({"REQUEST_ID": REQUEST, "RM_ORIGIN": "dev"}, "rm_origin 'dev' is not staging, prod or local"),
        ({"REQUEST_ID": REQUEST}, "request_id and rm_origin go together"),
        ({"RM_ORIGIN": "staging"}, "request_id and rm_origin go together"),
        ({"RM_ORIGIN": "local"}, "request_id and rm_origin go together"),
    ],
)
def test_publish_refused_inputs(tmp_path, env, message):
    result, out = _publish(tmp_path, **env)
    assert result.returncode == 1
    assert message in result.stderr
    assert out == {}


def test_an_unknown_mode_is_refused(tmp_path):
    result, out = _publish(tmp_path, MODE="release")
    assert result.returncode == 1
    assert "MODE must be prepare or publish" in result.stderr
    assert out == {}
