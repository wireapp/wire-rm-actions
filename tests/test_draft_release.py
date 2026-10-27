"""scripts/draft-release.sh against the fake gh: create the draft with its assets, resolve
and download it, publish it (replaced assets, make_latest, the tag born last)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import REPO, outputs

SCRIPT = "scripts/draft-release.sh"
SHA = "348ddc047bfdc977b554df64accc40495ee57bcb"
OTHER = "1" * 40
KEYS = (
    "REPO", "MODE", "VERSION", "TAG_PREFIX", "TARGET", "TITLE", "BODY_FILE", "PRERELEASE", "ASSETS",
    "RELEASE_ID", "EXPECTED_COMMIT", "ASSET_DIR", "DOWNLOAD", "MANIFEST_NAME", "REPLACE_ASSETS",
    "MAKE_LATEST", "SOURCE_REF", "LATEST_BRANCHES", "CREATE_ATTEMPTS", "CREATE_DELAY", "RUNNER_TEMP",
)
MANIFEST = {
    "version": "1.41.4",
    "artifacts": [
        {"type": "image", "repository": "quay.io/wire/example", "digest": "sha256:aa"},
        {"type": "chart", "file": "example-1.41.4.tgz", "sha256": "bb"},
    ],
    "documents": {
        "release_note": {"file": "release-note.md", "sha256": "cc"},
        "release_declaration": {"file": "release-declaration.json", "sha256": "dd"},
    },
}


@pytest.fixture
def files(tmp_path: Path) -> Path:
    d = tmp_path / "release"
    d.mkdir()
    (d / "release-manifest.json").write_text(json.dumps(MANIFEST))
    (d / "example-1.41.4.tgz").write_bytes(b"\x1f\x8bchart")
    (d / "release-note.md").write_text("# 1.41.4\n")
    (d / "release-declaration.json").write_text("{}\n")
    (d / "body.md").write_text("The body.\n")
    (d / "extra.txt").write_text("extra\n")
    return d


def _run(gh, tmp_path: Path, **env: str):
    runner_temp = tmp_path / "runner"
    runner_temp.mkdir(exist_ok=True)
    base = {"VERSION": "1.41.4", "CREATE_DELAY": "0", "RUNNER_TEMP": str(runner_temp)}
    return gh.run(SCRIPT, tmp_path, KEYS, **{**base, **env})


def _create(gh, tmp_path, files, **env):
    assets = "\n".join(str(files / n) for n in ("example-1.41.4.tgz", "release-manifest.json", "release-note.md", "release-declaration.json"))
    base = {"MODE": "create", "TARGET": SHA, "BODY_FILE": str(files / "body.md"), "ASSETS": assets + "\n"}
    return _run(gh, tmp_path, **{**base, **env})


def test_create(gh, tmp_path, files):
    summary = tmp_path / "summary.md"
    result = _create(gh, tmp_path, files, GITHUB_STEP_SUMMARY=str(summary))
    assert result.returncode == 0, result.stderr
    out = outputs(result)
    assert out["id"] == "101"
    assert out["tag"] == "v1.41.4"
    assert out["url"] == f"https://github.com/{REPO}/releases/tag/untagged-101"
    assert out["published-url"] == f"https://github.com/{REPO}/releases/tag/v1.41.4"
    release = gh.load()["releases"][0]
    assert release["draft"] is True and release["prerelease"] is False
    assert release["target_commitish"] == SHA
    assert release["name"] == "v1.41.4"
    assert release["body"] == "The body.\n"
    names = [a["name"] for a in gh.state["assets"]["101"]]
    assert names == ["example-1.41.4.tgz", "release-manifest.json", "release-note.md", "release-declaration.json"]
    assert "Draft release ready" in summary.read_text()


def test_create_prerelease_title_no_body(gh, tmp_path, files):
    result = _create(gh, tmp_path, files, VERSION="1.41.4-rc.2", TITLE="Example 1.41.4-rc.2", BODY_FILE="", ASSETS="")
    assert result.returncode == 0, result.stderr
    release = gh.load()["releases"][0]
    assert release["prerelease"] is True
    assert release["name"] == "Example 1.41.4-rc.2"
    assert release["body"] == ""
    assert gh.state["assets"]["101"] == []


def test_create_prerelease_forced(gh, tmp_path, files):
    assert _create(gh, tmp_path, files, PRERELEASE="true").returncode == 0
    assert gh.load()["releases"][0]["prerelease"] is True


def test_create_refuses_an_existing_release(gh, tmp_path, files):
    gh.state["releases"] = [{"id": 5, "tag_name": "v1.41.4", "draft": True}]
    result = _create(gh, tmp_path, files)
    assert result.returncode == 1
    assert "already exists for tag v1.41.4 (id(s): 5)" in result.stderr
    assert not any(c[:2] == ["release", "create"] for c in gh.calls())


def test_create_waits_for_the_list(gh, tmp_path, files):
    gh.state["list_lag"] = 3
    result = _create(gh, tmp_path, files)
    assert result.returncode == 0, result.stderr
    assert "has not caught up with v1.41.4 yet (attempt 1/5)" in result.stdout


def test_create_gives_up(gh, tmp_path, files):
    gh.state["list_lag"] = 10
    result = _create(gh, tmp_path, files, CREATE_ATTEMPTS="2")
    assert result.returncode == 1
    assert "must be deleted before preparing this version again" in result.stderr


@pytest.mark.parametrize(
    "env, message",
    [
        ({"TARGET": "dev"}, "is not a full commit sha"),
        ({"ASSETS": "/nonexistent/file.tgz"}, "not found"),
        ({"BODY_FILE": "/nonexistent/body.md"}, "body file"),
        ({"PRERELEASE": "maybe"}, "prerelease must be"),
        ({"VERSION": "v1.41.4"}, "is not a release version"),
        ({"MODE": "delete"}, "MODE must be"),
    ],
)
def test_create_invalid(gh, tmp_path, files, env, message):
    result = _create(gh, tmp_path, files, **env)
    assert result.returncode == 1
    assert message in result.stderr


def test_create_duplicate_asset_names(gh, tmp_path, files):
    other = tmp_path / "other"
    other.mkdir()
    (other / "release-note.md").write_text("x")
    result = _create(gh, tmp_path, files, ASSETS=f"{files / 'release-note.md'}\n{other / 'release-note.md'}")
    assert result.returncode == 1
    assert "two assets share the name" in result.stderr


@pytest.fixture
def draft(gh, tmp_path, files):
    assert _create(gh, tmp_path, files, ASSETS="\n".join(str(p) for p in sorted(files.glob("*")) if p.name != "body.md")).returncode == 0
    gh.load()
    for r in gh.state["releases"]:
        r.pop("new", None)
    return gh


def test_resolve_manifest_files(draft, tmp_path):
    result = _run(draft, tmp_path, MODE="resolve", DOWNLOAD="manifest-files", ASSET_DIR=str(tmp_path / "candidate"))
    assert result.returncode == 0, result.stderr
    out = outputs(result)
    assert out["id"] == "101"
    assert out["target-commitish"] == SHA
    assert out["prerelease"] == "false"
    assert out["tag-exists"] == "false"
    assert out["manifest"] == str(tmp_path / "candidate/release-manifest.json")
    got = sorted(p.name for p in (tmp_path / "candidate").iterdir())
    assert got == ["example-1.41.4.tgz", "release-declaration.json", "release-manifest.json", "release-note.md"]
    assert (tmp_path / "candidate/example-1.41.4.tgz").read_bytes() == b"\x1f\x8bchart"
    assert Path(out["body-file"]).read_text() == "The body.\n"


def test_resolve_by_id_manifest_only_default_dir(draft, tmp_path):
    result = _run(draft, tmp_path, MODE="resolve", RELEASE_ID="101", EXPECTED_COMMIT=SHA)
    assert result.returncode == 0, result.stderr
    out = outputs(result)
    assert out["asset-dir"] == str(tmp_path / "runner/release-assets")
    assert sorted(p.name for p in Path(out["asset-dir"]).iterdir()) == ["release-manifest.json"]


def test_resolve_all_and_extra(draft, tmp_path):
    result = _run(draft, tmp_path, MODE="resolve", DOWNLOAD="all", ASSET_DIR=str(tmp_path / "all"))
    assert result.returncode == 0, result.stderr
    assert "extra.txt" in [p.name for p in (tmp_path / "all").iterdir()]
    assert outputs(result)["manifest"].endswith("release-manifest.json")
    result = _run(draft, tmp_path, MODE="resolve", DOWNLOAD="none", ASSETS="extra.txt", ASSET_DIR=str(tmp_path / "one"))
    assert result.returncode == 0, result.stderr
    assert [p.name for p in (tmp_path / "one").iterdir()] == ["extra.txt"]
    assert outputs(result)["manifest"] == ""


def test_resolve_missing_asset(draft, tmp_path):
    result = _run(draft, tmp_path, MODE="resolve", DOWNLOAD="none", ASSETS="nope.tgz")
    assert result.returncode == 1
    assert "asset 'nope.tgz' not found" in result.stderr


def test_resolve_refuses_a_path_in_the_manifest(draft, tmp_path):
    asset = next(a for a in draft.state["assets"]["101"] if a["name"] == "release-manifest.json")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"artifacts": [{"type": "chart", "file": "../../etc/passwd"}]}))
    asset["file"] = str(bad)
    result = _run(draft, tmp_path, MODE="resolve", DOWNLOAD="manifest-files")
    assert result.returncode == 1
    assert "is not a plain file name" in result.stderr


@pytest.mark.parametrize(
    "change, env, message",
    [
        ({"draft": False}, {"RELEASE_ID": "101"}, "is not a draft"),
        ({"tag_name": "v9.9.9"}, {"RELEASE_ID": "101"}, "expected 'v1.41.4'"),
        ({}, {"EXPECTED_COMMIT": OTHER}, f"expected '{OTHER}'"),
        ({"draft": False}, {}, "expected exactly one draft release for tag v1.41.4, found 0"),
    ],
)
def test_resolve_refuses(draft, tmp_path, change, env, message):
    draft.state["releases"][0].update(change)
    result = _run(draft, tmp_path, MODE="resolve", **env)
    assert result.returncode == 1
    assert message in result.stderr


def test_resolve_two_drafts(draft, tmp_path):
    draft.state["releases"].append({**draft.state["releases"][0], "id": 102})
    result = _run(draft, tmp_path, MODE="resolve")
    assert result.returncode == 1
    assert "found 2" in result.stderr


def test_tag_state(draft, tmp_path):
    draft.state["refs"] = [{"ref": "refs/tags/v1.41.4", "object": {"type": "tag", "sha": "f" * 40}}]
    draft.state["tags"] = {"f" * 40: {"object": {"type": "commit", "sha": SHA}}}
    result = _run(draft, tmp_path, MODE="resolve")
    assert result.returncode == 0, result.stderr
    assert outputs(result)["tag-exists"] == "true"
    draft.state["tags"] = {"f" * 40: {"object": {"type": "commit", "sha": OTHER}}}
    result = _run(draft, tmp_path, MODE="resolve")
    assert result.returncode == 1
    assert f"already exists at {OTHER}" in result.stderr
    result = _run(draft, tmp_path, MODE="publish", RELEASE_ID="101", MAKE_LATEST="false")
    assert result.returncode == 1
    assert draft.load()["releases"][0]["draft"] is True


def test_publish(draft, tmp_path):
    completed = tmp_path / "release-manifest.completed.json"
    completed.write_text('{"publication": {}}\n')
    result = _run(
        draft, tmp_path, MODE="publish", RELEASE_ID="101", SOURCE_REF="dev",
        REPLACE_ASSETS=f"release-manifest.json={completed}\n",
    )
    assert result.returncode == 0, result.stderr
    out = outputs(result)
    assert out["make-latest"] == "true"
    assert out["url"] == f"https://github.com/{REPO}/releases/tag/v1.41.4"
    state = draft.load()
    release = state["releases"][0]
    assert release["draft"] is False and release["make_latest"] == "true"
    assert state["refs"][-1] == {"ref": "refs/tags/v1.41.4", "object": {"type": "commit", "sha": SHA}}
    manifests = [a for a in state["assets"]["101"] if a["name"] == "release-manifest.json"]
    assert len(manifests) == 1
    assert Path(manifests[0]["file"]).read_text() == '{"publication": {}}\n'
    assert manifests[0]["content_type"] == ["Content-Type: application/json"]
    upload = next(c for c in draft.calls() if "POST" in c)
    assert f"https://uploads.github.com/repos/{REPO}/releases/101/assets?name=release-manifest.json" in upload
    # The tag is born last: the PATCH is the last call.
    assert draft.calls()[-1][:3] == ["api", "--method", "PATCH"]


def test_publish_replace_plain_path(draft, tmp_path):
    new = tmp_path / "notes.md"
    new.write_text("new")
    result = _run(draft, tmp_path, MODE="publish", MAKE_LATEST="false", REPLACE_ASSETS=str(new))
    assert result.returncode == 0, result.stderr
    assert "notes.md" in [a["name"] for a in draft.load()["assets"]["101"]]


@pytest.mark.parametrize(
    "env, refs, latest",
    [
        ({"SOURCE_REF": "dev"}, ["v1.41.3", "v1.42.0-rc.1", "v1.9.10"], "true"),
        ({"SOURCE_REF": "dev"}, ["v1.41.3", "v1.41.10"], "false"),
        ({"SOURCE_REF": "dev"}, ["v2.0.0"], "false"),
        ({"SOURCE_REF": "release/1.41"}, [], "false"),
        ({"SOURCE_REF": "main", "LATEST_BRANCHES": "^(dev|main)$"}, [], "true"),
        ({"LATEST_BRANCHES": ""}, [], "true"),
        ({"VERSION": "1.41.4-rc.1"}, [], "false"),
        ({"MAKE_LATEST": "legacy"}, ["v9.0.0"], "legacy"),
        ({"MAKE_LATEST": "true"}, ["v9.0.0"], "true"),
    ],
)
def test_make_latest(draft, tmp_path, env, refs, latest):
    if "VERSION" in env:
        draft.state["releases"][0]["tag_name"] = "v" + env["VERSION"]
    draft.state["refs"] = [{"ref": f"refs/tags/{t}", "object": {"type": "commit", "sha": OTHER}} for t in refs]
    result = _run(draft, tmp_path, MODE="publish", **env)
    assert result.returncode == 0, result.stderr
    assert outputs(result)["make-latest"] == latest
    if latest == "false" and refs and env.get("SOURCE_REF") == "dev":
        assert "keeps the Latest badge" in result.stderr


def test_make_latest_auto_needs_the_source_ref(draft, tmp_path):
    result = _run(draft, tmp_path, MODE="publish")
    assert result.returncode == 1
    assert "needs the source-ref" in result.stderr
    assert draft.load()["releases"][0]["draft"] is True


def test_publish_refuses_a_published_release(draft, tmp_path):
    draft.state["releases"][0]["draft"] = False
    result = _run(draft, tmp_path, MODE="publish", RELEASE_ID="101", MAKE_LATEST="false")
    assert result.returncode == 1
    assert "is not a draft" in result.stderr


def test_tag_prefix(gh, tmp_path, files):
    result = _create(gh, tmp_path, files, TAG_PREFIX="chart-")
    assert result.returncode == 0, result.stderr
    assert gh.load()["releases"][0]["tag_name"] == "chart-1.41.4"
    for r in gh.state["releases"]:
        r.pop("new", None)
    result = _run(gh, tmp_path, MODE="publish", TAG_PREFIX="chart-", SOURCE_REF="dev")
    assert result.returncode == 0, result.stderr
    assert outputs(result)["tag"] == "chart-1.41.4"


def test_token_is_required(gh, tmp_path, files):
    result = _create(gh, tmp_path, files, GH_TOKEN="")
    assert result.returncode == 1
