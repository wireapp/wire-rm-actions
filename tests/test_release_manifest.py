"""scripts/release-manifest.sh: the frozen release manifest (write), its check
against downloaded release assets (verify) and the publication block
(complete)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/release-manifest.sh"
COMMIT = "348ddc047bfdc977b554df64accc40495ee57bcb"
UUID4 = "123e4567-e89b-42d3-a456-426614174000"
IMAGE_DIGEST = "sha256:" + hashlib.sha256(b"image").hexdigest()
CHART_DIGEST = "sha256:" + hashlib.sha256(b"chart").hexdigest()
COMPATIBILITY = """\
providesApis:
  - api: example/api
    versions: ["1"]
consumesApis:
  - api: wire-server/admin-api
    versions: "1"
    class: mandatory
dependsOn:
  - resource: sqs
    range: "*"
    class: mandatory
includes: []
"""
ENV_KEYS = (
    "MODE", "MANIFEST", "COMPONENT", "VERSION", "RELEASE_TYPE", "TAG_PREFIX", "RELEASE_BRANCHES",
    "SOURCE_REPOSITORY", "SOURCE_REF", "SOURCE_COMMIT", "IMAGE_REPOSITORY", "IMAGE_DIGEST",
    "IMAGE_CANDIDATE_TAG", "CHART_REPOSITORY", "CHART_FILE", "CHART_SHA256", "CHART_DIGEST",
    "COMPATIBILITY_FILE", "DOCUMENTS_JSON", "REQUEST_ID", "RM_ORIGIN", "ASSET_DIR", "RUN_URL",
    "DIGESTS_JSON", "OUT", "PUBLISHED_AT", "BUILD_WORKFLOW", "BUILD_RUN_ID", "BUILD_RUN_URL",
    "BUILD_CREATED_AT", "INPUTS_JSON", "EXTRA_ARTIFACTS_JSON", "EXPIRES_AFTER", "GITHUB_OUTPUT",
    "CHECK_SOURCE_BRANCH",
)


def _run(cwd: Path, **env: str) -> subprocess.CompletedProcess:
    clean = {k: v for k, v in os.environ.items() if k not in ENV_KEYS}
    return subprocess.run(["bash", str(SCRIPT)], cwd=cwd, env={**clean, **env}, capture_output=True, text=True)


def _outputs(result: subprocess.CompletedProcess) -> dict[str, str]:
    out = {}
    for line in result.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.replace("-", "").isalnum():
            out[key] = value
    return out


@pytest.fixture
def work(tmp_path: Path) -> Path:
    (tmp_path / "publication").mkdir()
    (tmp_path / "publication/compatibility.yaml").write_text(COMPATIBILITY)
    (tmp_path / "example-1.41.4-rc.1.tgz").write_text("chart content\n")
    (tmp_path / "release-note.md").write_text("# note\n")
    return tmp_path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_rc(work: Path, **changes: str) -> dict[str, str]:
    return {
        "MODE": "write", "MANIFEST": "rc.json", "COMPONENT": "example", "VERSION": "1.41.4-rc.1",
        "RELEASE_TYPE": "rc", "SOURCE_REPOSITORY": "https://github.com/wireapp/example", "SOURCE_REF": "dev",
        "SOURCE_COMMIT": COMMIT, "IMAGE_REPOSITORY": "quay.io/wire/example", "IMAGE_DIGEST": IMAGE_DIGEST,
        "IMAGE_CANDIDATE_TAG": "1.41.4-rc.1-candidate-42", "CHART_REPOSITORY": "oci://quay.io/wire/charts/stable/example",
        "CHART_FILE": "example-1.41.4-rc.1.tgz", "CHART_SHA256": _sha(work / "example-1.41.4-rc.1.tgz"),
        "BUILD_WORKFLOW": ".github/workflows/prepare-release.yml", "BUILD_RUN_ID": "42",
        "BUILD_RUN_URL": "https://github.com/wireapp/example/actions/runs/42", "BUILD_CREATED_AT": "2026-10-10T10:00:00Z",
        "DOCUMENTS_JSON": json.dumps(
            {"release_note": {"file": "release-note.md", "sha256": _sha(work / "release-note.md"), "source": "repository"}}
        ),
        **changes,
    }


def _write_dev(**changes: str) -> dict[str, str]:
    return {
        "MODE": "write", "MANIFEST": "dev.json", "COMPONENT": "example", "VERSION": "1.41.5-20261014120000.g348ddc0",
        "RELEASE_TYPE": "dev", "SOURCE_REPOSITORY": "https://github.com/wireapp/example", "SOURCE_REF": "dev",
        "SOURCE_COMMIT": COMMIT, "IMAGE_REPOSITORY": "quay.io/wire/example", "IMAGE_DIGEST": IMAGE_DIGEST,
        "CHART_REPOSITORY": "oci://quay.io/wire/charts/dev/example", "CHART_DIGEST": CHART_DIGEST,
        "BUILD_WORKFLOW": ".github/workflows/dev.yml", "BUILD_RUN_ID": "43",
        "BUILD_RUN_URL": "https://github.com/wireapp/example/actions/runs/43", **changes,
    }


# --- write --------------------------------------------------------------------------


def test_write_a_prerelease(work: Path):
    result = _run(work, **_write_rc(work))
    assert result.returncode == 0, result.stderr
    doc = json.loads((work / "rc.json").read_text())
    assert doc["schemaVersion"] == "wire.component-release-manifest/v1alpha1"
    assert (doc["component"], doc["version"], doc["kind"], doc["stage"]) == ("example", "1.41.4-rc.1", "prerelease", "rc")
    assert doc["source"]["tag"] == "v1.41.4-rc.1"
    assert [a["type"] for a in doc["artifacts"]] == ["image", "chart"]
    assert doc["compatibility"]["includes"] == []
    assert [r.get("interface") or r.get("capability") for r in doc["compatibility"]["requires"]] == [
        "wire-server/admin-api", "sqs",
    ]
    assert doc["request_id"] is None and doc["rm_origin"] is None
    assert doc["inputs"] == [] and "expires_at" not in doc
    assert _outputs(result)["manifest"] == "rc.json"


def test_write_a_ga_from_the_release_manager_with_another_tag_prefix(work: Path):
    result = _run(
        work, **_write_rc(work, MANIFEST="ga.json", VERSION="1.41.4", RELEASE_TYPE="ga",
                          REQUEST_ID=UUID4, RM_ORIGIN="prod", TAG_PREFIX="example-")
    )
    assert result.returncode == 0, result.stderr
    doc = json.loads((work / "ga.json").read_text())
    assert doc["kind"] == "ga" and "stage" not in doc
    assert doc["source"]["tag"] == "example-1.41.4"
    assert (doc["request_id"], doc["rm_origin"]) == (UUID4, "prod")


def test_write_a_dev_build(work: Path):
    result = _run(work, **_write_dev())
    assert result.returncode == 0, result.stderr
    doc = json.loads((work / "dev.json").read_text())
    assert doc["kind"] == "dev" and "stage" not in doc and doc["source"]["tag"] is None
    assert doc["artifacts"] == [
        {"type": "image", "repository": "quay.io/wire/example", "tag": doc["version"], "digest": IMAGE_DIGEST},
        {"type": "chart", "repository": "oci://quay.io/wire/charts/dev/example", "version": doc["version"], "digest": CHART_DIGEST},
    ]


BUNDLE = {"type": "bundle", "file": "example.zip", "sha256": hashlib.sha256(b"bundle").hexdigest()}
CONFIG_INPUT = {"name": "config", "repository": "https://github.com/wireapp/config", "ref": "main", "commit": COMMIT}


def test_write_the_inputs_and_the_extra_artifacts(work: Path):
    result = _run(work, **_write_rc(work, INPUTS_JSON=json.dumps([CONFIG_INPUT]), EXTRA_ARTIFACTS_JSON=json.dumps([BUNDLE])))
    assert result.returncode == 0, result.stderr
    doc = json.loads((work / "rc.json").read_text())
    assert doc["inputs"] == [CONFIG_INPUT]
    assert [a["type"] for a in doc["artifacts"]] == ["image", "chart", "bundle"]
    assert doc["artifacts"][2] == BUNDLE


def test_write_a_dev_build_with_extra_artifacts_keeps_the_image_and_the_chart_first(work: Path):
    result = _run(work, **_write_dev(EXTRA_ARTIFACTS_JSON=json.dumps([BUNDLE])))
    assert result.returncode == 0, result.stderr
    doc = json.loads((work / "dev.json").read_text())
    assert [a["type"] for a in doc["artifacts"]] == ["image", "chart", "bundle"]


def test_write_a_dev_build_without_expiry_has_no_expires_at(work: Path):
    assert _run(work, **_write_dev()).returncode == 0
    assert "expires_at" not in json.loads((work / "dev.json").read_text())


@pytest.mark.parametrize(
    ("after", "expires_at"),
    [
        ("90d", "2027-01-12T12:00:00Z"),
        ("36h", "2026-10-16T00:00:00Z"),
        ("2w", "2026-10-28T12:00:00Z"),
    ],
)
def test_write_a_dev_build_that_expires(work: Path, after: str, expires_at: str):
    result = _run(work, **_write_dev(EXPIRES_AFTER=after, BUILD_CREATED_AT="2026-10-14T12:00:00Z"))
    assert result.returncode == 0, result.stderr
    doc = json.loads((work / "dev.json").read_text())
    assert doc["expires_at"] == expires_at
    assert doc["build"]["created_at"] == "2026-10-14T12:00:00Z"


def test_write_a_dev_build_that_expires_from_now(work: Path):
    result = _run(work, **_write_dev(EXPIRES_AFTER="1d"))
    assert result.returncode == 0, result.stderr
    doc = json.loads((work / "dev.json").read_text())
    assert doc["expires_at"].endswith("Z") and doc["expires_at"] > doc["build"]["created_at"]


def test_write_keeps_the_includes_of_the_file(work: Path):
    (work / "with-includes.yaml").write_text(
        COMPATIBILITY.replace("includes: []\n", "includes:\n  - component: other\n    version: 1.0.0\n    reason: Shipped inside.\n")
    )
    result = _run(work, **_write_rc(work, COMPATIBILITY_FILE="with-includes.yaml"))
    assert result.returncode == 0, result.stderr
    assert json.loads((work / "rc.json").read_text())["compatibility"]["includes"] == [
        {"component": "other", "version": "1.0.0", "reason": "Shipped inside."}
    ]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"COMPONENT": ""}, "COMPONENT is required"),
        ({"IMAGE_DIGEST": ""}, "manifest field .artifacts[0].digest is empty"),
        ({"IMAGE_DIGEST": "sha256:abc"}, "image digest is not a sha256 digest"),
        ({"SOURCE_COMMIT": "348ddc04"}, "source commit is not a full sha"),
        ({"VERSION": "1.41.4"}, "does not match the release type"),
        ({"RELEASE_TYPE": "nightly"}, "RELEASE_TYPE must be one of ga, alpha, beta, rc, dev"),
        ({"RM_ORIGIN": "prod"}, "RM_ORIGIN is set without REQUEST_ID"),
        ({"REQUEST_ID": UUID4}, "RM_ORIGIN is required with REQUEST_ID"),
        ({"DOCUMENTS_JSON": "null"}, "DOCUMENTS_JSON must be a JSON object"),
        ({"COMPATIBILITY_FILE": "none.yaml"}, "none.yaml: compatibility file does not exist"),
        ({"CHART_SHA256": ""}, "manifest field .artifacts[1].sha256 is empty"),
    ],
)
def test_write_refuses(work: Path, changes: dict, message: str):
    result = _run(work, **_write_rc(work, **changes))
    assert result.returncode == 1
    assert message in result.stderr
    assert not (work / "rc.json").exists()


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"VERSION": "1.41.5"}, "is not a dev version"),
        ({"CHART_DIGEST": ""}, "chart digest is not a sha256 digest"),
        ({"REQUEST_ID": UUID4, "RM_ORIGIN": "prod"}, "a dev build has no REQUEST_ID nor RM_ORIGIN"),
    ],
)
def test_write_dev_refuses(work: Path, changes: dict, message: str):
    result = _run(work, **_write_dev(**changes))
    assert result.returncode == 1
    assert message in result.stderr


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"INPUTS_JSON": "{}"}, "INPUTS_JSON must be a JSON array of objects with a name"),
        ({"INPUTS_JSON": "null"}, "INPUTS_JSON must be a JSON array of objects with a name"),
        ({"INPUTS_JSON": '[{"repository": "x"}]'}, "INPUTS_JSON must be a JSON array of objects with a name"),
        ({"INPUTS_JSON": '[{"name": ""}]'}, "INPUTS_JSON must be a JSON array of objects with a name"),
        ({"EXTRA_ARTIFACTS_JSON": "{}"}, "EXTRA_ARTIFACTS_JSON must be a JSON array"),
        ({"EXTRA_ARTIFACTS_JSON": json.dumps([{**BUNDLE, "type": "image"}])}, "EXTRA_ARTIFACTS_JSON must be a JSON array"),
        ({"EXTRA_ARTIFACTS_JSON": json.dumps([{**BUNDLE, "type": "chart"}])}, "EXTRA_ARTIFACTS_JSON must be a JSON array"),
        ({"EXTRA_ARTIFACTS_JSON": json.dumps([{**BUNDLE, "file": "../example.zip"}])}, "EXTRA_ARTIFACTS_JSON must be a JSON array"),
        ({"EXTRA_ARTIFACTS_JSON": json.dumps([{**BUNDLE, "file": ".hidden"}])}, "EXTRA_ARTIFACTS_JSON must be a JSON array"),
        ({"EXTRA_ARTIFACTS_JSON": json.dumps([{**BUNDLE, "sha256": "abc"}])}, "EXTRA_ARTIFACTS_JSON must be a JSON array"),
        ({"EXTRA_ARTIFACTS_JSON": json.dumps([{**BUNDLE, "url": "https://x"}])}, "EXTRA_ARTIFACTS_JSON must be a JSON array"),
        ({"EXPIRES_AFTER": "90d"}, "EXPIRES_AFTER is for a dev build only"),
    ],
)
def test_write_refuses_inputs_extras_and_expiry(work: Path, changes: dict, message: str):
    result = _run(work, **_write_rc(work, **changes))
    assert result.returncode == 1
    assert message in result.stderr
    assert not (work / "rc.json").exists()


@pytest.mark.parametrize("after", ["90", "0d", "90m", "d", "-1d", "1.5d", "90 d"])
def test_write_dev_refuses_a_bad_expiry(work: Path, after: str):
    result = _run(work, **_write_dev(EXPIRES_AFTER=after))
    assert result.returncode == 1
    assert "EXPIRES_AFTER must be a number of hours, days or weeks" in result.stderr
    assert not (work / "dev.json").exists()


def test_write_dev_refuses_an_expiry_without_an_iso_build_date(work: Path):
    result = _run(work, **_write_dev(EXPIRES_AFTER="90d", BUILD_CREATED_AT="2026-10-14 12:00"))
    assert result.returncode == 1
    assert "is not YYYY-MM-DDTHH:MM:SSZ, needed with EXPIRES_AFTER" in result.stderr


def test_write_refuses_a_compatibility_file_without_consumes_or_with_bad_includes(work: Path):
    (work / "partial.yaml").write_text("providesApis: []\n")
    (work / "bad.yaml").write_text("providesApis: []\nconsumesApis: []\ndependsOn: []\nincludes: {}\n")
    assert "consumesApis must be a list ([] when empty)" in _run(work, **_write_rc(work, COMPATIBILITY_FILE="partial.yaml")).stderr
    assert "includes must be a list" in _run(work, **_write_rc(work, COMPATIBILITY_FILE="bad.yaml")).stderr


def test_write_converts_the_publication_file(work: Path):
    (work / "publication/compatibility.yaml").write_text(
        "providesApis:\n  - api: example/api\n    versions: {supported: [1, 2]}\n"
        "consumesApis: []\ndependsOn:\n  - resource: sqs\n    range: '*'\n    class: mandatory\nincludes: []\n"
    )
    result = _run(work, **_write_rc(work))
    assert result.returncode == 0, result.stderr
    compatibility = json.loads((work / "rc.json").read_text())["compatibility"]
    assert compatibility == {
        "provides": [{"interface": "example/api", "supported": "1-2"}],
        "requires": [{"capability": "sqs", "range": "*", "class": "mandatory"}],
        "includes": [],
    }
    assert not any(line.startswith(("file=", "format=")) for line in result.stdout.splitlines())


def test_write_refuses_the_former_root_file(work: Path):
    (work / "publication/compatibility.yaml").unlink()
    (work / "compatibility.yaml").write_text("provides: []\nrequires: []\n")
    result = _run(work, **_write_rc(work))
    assert result.returncode == 1
    assert "the root compatibility.yaml (provides, requires) is the former layout" in result.stderr
    assert "the compatibility file was refused" in result.stderr



# --- verify -------------------------------------------------------------------------


@pytest.fixture
def written(work: Path) -> Path:
    assert _run(work, **_write_rc(work)).returncode == 0
    return work


def test_verify_the_assets(written: Path):
    result = _run(written, MODE="verify", MANIFEST="rc.json", ASSET_DIR=".", VERSION="1.41.4-rc.1", SOURCE_COMMIT=COMMIT)
    assert result.returncode == 0, result.stderr
    assert "Verified manifest for v1.41.4-rc.1 @ 348ddc0 (prerelease rc)" in result.stdout
    out = _outputs(result)
    assert (out["type"], out["source-ref"], out["chart-file"], out["image-digest"], out["note-file"]) == (
        "rc", "dev", "example-1.41.4-rc.1.tgz", IMAGE_DIGEST, "release-note.md",
    )


def test_verify_without_extra_artifacts_outputs_an_empty_list(written: Path):
    result = _run(written, MODE="verify", MANIFEST="rc.json", ASSET_DIR=".")
    assert result.returncode == 0, result.stderr
    assert _outputs(result)["extra-artifacts-json"] == "[]"


@pytest.fixture
def written_with_bundle(work: Path) -> Path:
    (work / "example.zip").write_bytes(b"bundle")
    assert _run(work, **_write_rc(work, EXTRA_ARTIFACTS_JSON=json.dumps([BUNDLE]))).returncode == 0
    return work


def test_verify_the_extra_artifacts(written_with_bundle: Path):
    result = _run(written_with_bundle, MODE="verify", MANIFEST="rc.json", ASSET_DIR=".")
    assert result.returncode == 0, result.stderr
    assert json.loads(_outputs(result)["extra-artifacts-json"]) == [{**BUNDLE, "path": "./example.zip"}]


def test_verify_refuses_a_missing_extra_artifact(written_with_bundle: Path):
    (written_with_bundle / "example.zip").unlink()
    result = _run(written_with_bundle, MODE="verify", MANIFEST="rc.json", ASSET_DIR=".")
    assert result.returncode == 1
    assert "bundle './example.zip' was not downloaded" in result.stderr


def test_verify_refuses_a_changed_extra_artifact(written_with_bundle: Path):
    (written_with_bundle / "example.zip").write_bytes(b"tampered")
    result = _run(written_with_bundle, MODE="verify", MANIFEST="rc.json", ASSET_DIR=".")
    assert result.returncode == 1
    assert "bundle 'example.zip' sha256" in result.stderr
    assert "refusing to publish" in result.stderr


@pytest.mark.parametrize(
    ("artifact", "message"),
    [
        ({"type": "bundle", "file": "../x.zip", "sha256": BUNDLE["sha256"]}, "is not a plain name"),
        ({"type": "bundle", "file": "example.zip", "sha256": "abc"}, "is not a hex sha256"),
        ({"type": "bundle", "file": "", "sha256": BUNDLE["sha256"]}, "is not a plain name"),
        ({"type": "image", "file": "example.zip", "sha256": BUNDLE["sha256"]}, "is not an extra artifact type"),
    ],
)
def test_verify_refuses_a_malformed_extra_artifact(written_with_bundle: Path, artifact: dict, message: str):
    doc = json.loads((written_with_bundle / "rc.json").read_text())
    doc["artifacts"][2] = artifact
    (written_with_bundle / "rc.json").write_text(json.dumps(doc))
    result = _run(written_with_bundle, MODE="verify", MANIFEST="rc.json", ASSET_DIR=".")
    assert result.returncode == 1
    assert message in result.stderr


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"VERSION": "1.41.5"}, "does not match the requested version '1.41.5'"),
        ({"SOURCE_COMMIT": "0" * 40}, "does not match the draft target"),
        ({"TAG_PREFIX": "example-"}, "manifest source.tag is not 'example-1.41.4-rc.1'"),
        ({"RELEASE_BRANCHES": "^main$"}, "is not a releasable branch"),
        ({"ASSET_DIR": "empty"}, "was not downloaded"),
    ],
)
def test_verify_refuses(written: Path, env: dict, message: str):
    (written / "empty").mkdir()
    result = _run(written, MODE="verify", MANIFEST="rc.json", **{"ASSET_DIR": ".", **env})
    assert result.returncode == 1
    assert message in result.stderr


def test_verify_refuses_a_changed_asset(written: Path):
    (written / "example-1.41.4-rc.1.tgz").write_text("tampered\n")
    result = _run(written, MODE="verify", MANIFEST="rc.json", ASSET_DIR=".")
    assert result.returncode == 1
    assert "chart package sha256" in result.stderr


def test_verify_refuses_a_changed_document(written: Path):
    (written / "release-note.md").write_text("# other\n")
    result = _run(written, MODE="verify", MANIFEST="rc.json", ASSET_DIR=".")
    assert result.returncode == 1
    assert "document 'release-note.md' sha256" in result.stderr


# --- verify, stale source ----------------------------------------------------------


def _git(cwd: Path, *args: str) -> str:
    env = {
        **os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org",
    }
    out = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def _commit(cwd: Path, name: str) -> str:
    (cwd / name).write_text(name)
    _git(cwd, "add", name)
    _git(cwd, "commit", "-q", "-m", name)
    return _git(cwd, "rev-parse", "HEAD")


@pytest.fixture
def repo(work: Path) -> tuple[Path, str]:
    """The work directory as a git repository; returns it with its first commit, which the manifest names."""
    _git(work, "init", "-q", "-b", "dev")
    first = _commit(work, "first")
    assert _run(work, **_write_rc(work, SOURCE_COMMIT=first)).returncode == 0
    return work, first


def _verify_stale(work: Path, **env: str) -> subprocess.CompletedProcess:
    return _run(work, **{"MODE": "verify", "MANIFEST": "rc.json", "ASSET_DIR": ".", "CHECK_SOURCE_BRANCH": "true", **env})


def test_verify_checks_a_source_that_is_still_an_ancestor(repo: tuple[Path, str]):
    work, first = repo
    _git(work, "update-ref", "refs/remotes/origin/dev", _commit(work, "second"))
    result = _verify_stale(work)
    assert result.returncode == 0, result.stderr
    assert f"Source commit {first} is still an ancestor of origin/dev." in result.stdout


def test_verify_checks_a_source_at_the_tip(repo: tuple[Path, str]):
    work, _ = repo
    _git(work, "update-ref", "refs/remotes/origin/dev", "HEAD")
    assert _verify_stale(work).returncode == 0


def test_verify_refuses_a_stale_source(repo: tuple[Path, str]):
    work, first = repo
    _git(work, "checkout", "-q", "--orphan", "rewritten")
    unrelated = _commit(work, "unrelated")
    _git(work, "update-ref", "refs/remotes/origin/dev", unrelated)
    result = _verify_stale(work)
    assert result.returncode == 1
    assert f"prepared source commit {first} is no longer an ancestor of origin/dev: the candidate is stale and must be prepared again" in result.stderr


def test_verify_refuses_a_branch_that_was_not_fetched(repo: tuple[Path, str]):
    result = _verify_stale(repo[0])
    assert result.returncode == 1
    assert "branch 'dev' is not in the checkout" in result.stderr


def test_verify_does_not_look_at_the_branch_by_default(repo: tuple[Path, str]):
    result = _run(repo[0], MODE="verify", MANIFEST="rc.json", ASSET_DIR=".")
    assert result.returncode == 0, result.stderr
    assert "ancestor" not in result.stdout


def test_verify_refuses_an_unknown_check_source_branch(repo: tuple[Path, str]):
    result = _verify_stale(repo[0], CHECK_SOURCE_BRANCH="yes")
    assert result.returncode == 1
    assert "CHECK_SOURCE_BRANCH must be true or false" in result.stderr


# --- complete -----------------------------------------------------------------------


def test_complete_in_place_and_again(written: Path):
    digests = json.dumps({"oci://quay.io/wire/charts/stable/example:1.41.4-rc.1": CHART_DIGEST})
    env = {"MODE": "complete", "MANIFEST": "rc.json", "PUBLISHED_AT": "2026-10-11T09:30:00Z",
           "RUN_URL": "https://x/1", "DIGESTS_JSON": digests}
    first = _run(written, **env)
    assert first.returncode == 0, first.stderr
    doc = json.loads((written / "rc.json").read_text())
    assert doc["publication"] == {"published_at": "2026-10-11T09:30:00Z", "run_url": "https://x/1", "digests": json.loads(digests)}
    again = _run(written, **env)
    assert again.returncode == 0, again.stderr
    assert json.loads((written / "rc.json").read_text()) == doc


def test_complete_to_another_file(written: Path):
    result = _run(written, MODE="complete", MANIFEST="rc.json", OUT="completed.json", RUN_URL="https://x/1")
    assert result.returncode == 0, result.stderr
    assert _outputs(result)["manifest"] == "completed.json"
    assert "publication" not in json.loads((written / "rc.json").read_text())


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"RUN_URL": ""}, "RUN_URL is required"),
        ({"RUN_URL": "https://x/1", "DIGESTS_JSON": '{"a":"b"}'}, "DIGESTS_JSON must be an object of sha256 digests"),
    ],
)
def test_complete_refuses(written: Path, env: dict, message: str):
    result = _run(written, MODE="complete", MANIFEST="rc.json", **env)
    assert result.returncode == 1
    assert message in result.stderr


def test_an_unknown_mode_is_refused(work: Path):
    result = _run(work, MODE="other")
    assert result.returncode == 1
    assert "MODE must be write, verify or complete" in result.stderr
