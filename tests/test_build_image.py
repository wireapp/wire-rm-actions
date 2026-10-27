"""scripts/build-image.sh against a fake docker first on PATH."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/build-image.sh"
VERSION = "1.41.5-20261013120000.gabcdef0"
SHA = "a" * 40
DIGEST = "sha256:" + "1" * 64
IMAGE = "quay.io/wire/my-component"
CREATED = "2026-10-21T15:30:00Z"

# Records each call as one line (arguments separated by a tab), then answers
# like docker would. FAKE_PRESENT=1 makes the tag already in the registry; a
# build makes it present at FAKE_DIGEST, and writes FAKE_BUILT_DIGEST (default
# FAKE_DIGEST) to the metadata file.
FAKE_DOCKER = r"""#!/usr/bin/env bash
set -euo pipefail
(IFS=$'\t'; echo "$*") >>"$DOCKER_LOG"
case "$1 $2" in
"buildx imagetools")
  if [[ ${FAKE_PRESENT:-} == 1 || -f $DOCKER_STATE ]]; then
    echo "${FAKE_REGISTRY_DIGEST:-$FAKE_DIGEST}"
  else
    echo "ERROR: $4: not found" >&2
    exit 1
  fi
  ;;
"buildx build")
  meta=""
  prev=""
  for a in "$@"; do
    [[ $prev == --metadata-file ]] && meta=$a
    prev=$a
  done
  printf '{\n  "containerimage.digest": "%s"\n}\n' "${FAKE_BUILT_DIGEST:-$FAKE_DIGEST}" >"$meta"
  touch "$DOCKER_STATE"
  ;;
*)
  echo "fake docker: unexpected call: $*" >&2
  exit 2
  ;;
esac
"""


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    (tmp_path / "Dockerfile").write_text("FROM scratch\n")
    output = tmp_path / "github-output"
    output.touch()
    clean = {k: v for k, v in os.environ.items() if not k.startswith("GITHUB_")}
    return {
        **clean,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "DOCKER_LOG": str(tmp_path / "docker.log"),
        "DOCKER_STATE": str(tmp_path / "pushed"),
        "GITHUB_OUTPUT": str(output),
        "IMAGE": IMAGE,
        "DOCKERFILE": str(tmp_path / "Dockerfile"),
        "CONTEXT": str(tmp_path),
        "VERSION": VERSION,
        "REVISION": SHA,
        "CREATED": CREATED,
        "FAKE_DIGEST": DIGEST,
    }


def _run(env: dict[str, str], **extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT)], env={**env, **extra}, capture_output=True, text=True
    )


def _calls(env: dict[str, str]) -> list[list[str]]:
    log = Path(env["DOCKER_LOG"])
    return [line.split("\t") for line in log.read_text().splitlines()] if log.exists() else []


def _build(env: dict[str, str]) -> list[str]:
    return next(c for c in _calls(env) if c[:2] == ["buildx", "build"])


def _pairs(argv: list[str], flag: str) -> list[str]:
    return [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == flag]


def _outputs(env: dict[str, str]) -> dict[str, str]:
    lines = Path(env["GITHUB_OUTPUT"]).read_text().splitlines()
    return dict(line.split("=", 1) for line in lines)


def test_new_tag_is_built_and_pushed(env):
    result = _run(env, GITHUB_REPOSITORY="wireapp/my-component")
    assert result.returncode == 0, result.stderr
    build = _build(env)
    assert _pairs(build, "--file") == [env["DOCKERFILE"]]
    assert _pairs(build, "--tag") == [f"{IMAGE}:{VERSION}"]
    assert _pairs(build, "--platform") == ["linux/amd64"]
    assert {"--push", "--provenance=mode=max", "--sbom=true"} <= set(build)
    assert build[-1] == env["CONTEXT"]
    assert _pairs(build, "--label") == [
        f"org.opencontainers.image.version={VERSION}",
        f"org.opencontainers.image.revision={SHA}",
        "org.opencontainers.image.source=https://github.com/wireapp/my-component",
        f"org.opencontainers.image.created={CREATED}",
    ]
    assert _pairs(build, "--annotation") == [
        f"manifest:org.opencontainers.image.version={VERSION}",
        f"manifest:org.opencontainers.image.revision={SHA}",
        "manifest:org.opencontainers.image.source=https://github.com/wireapp/my-component",
        f"manifest:org.opencontainers.image.created={CREATED}",
    ]
    assert _outputs(env) == {
        "image": IMAGE,
        "tag": VERSION,
        "digest": DIGEST,
        "ref": f"{IMAGE}@{DIGEST}",
        "status": "pushed",
    }
    assert f"digest={DIGEST}" in result.stdout.splitlines()


def test_present_tag_is_not_rebuilt(env):
    result = _run(env, FAKE_PRESENT="1")
    assert result.returncode == 0, result.stderr
    assert not any(c[:2] == ["buildx", "build"] for c in _calls(env))
    assert "already pushed, not rebuilt nor overwritten" in result.stdout
    assert _outputs(env)["status"] == "present"
    assert _outputs(env)["digest"] == DIGEST


def test_tag_input_wins_over_version(env):
    candidate = "1.41.5-candidate-123"
    result = _run(env, TAG=candidate)
    assert result.returncode == 0, result.stderr
    build = _build(env)
    assert _pairs(build, "--tag") == [f"{IMAGE}:{candidate}"]
    assert f"org.opencontainers.image.version={VERSION}" in _pairs(build, "--label")
    assert _outputs(env)["tag"] == candidate


def test_multi_platform_annotates_the_index(env):
    result = _run(env, PLATFORMS="linux/amd64,linux/arm64")
    assert result.returncode == 0, result.stderr
    build = _build(env)
    assert _pairs(build, "--platform") == ["linux/amd64,linux/arm64"]
    assert all(a.startswith("index,manifest:") for a in _pairs(build, "--annotation"))


def test_build_args_contexts_and_target(env):
    result = _run(
        env,
        BUILD_ARGS="REVISION=1.2.3\n  NODE_ENV=production\n\n",
        BUILD_CONTEXTS="bundle=server/dist\n",
        TARGET="runtime",
    )
    assert result.returncode == 0, result.stderr
    build = _build(env)
    assert _pairs(build, "--build-arg") == ["REVISION=1.2.3", "NODE_ENV=production"]
    assert _pairs(build, "--build-context") == ["bundle=server/dist"]
    assert _pairs(build, "--target") == ["runtime"]


def test_attestations_can_be_turned_off(env):
    result = _run(env, PROVENANCE="false", SBOM="false")
    assert result.returncode == 0, result.stderr
    build = _build(env)
    assert {"--provenance=false", "--sbom=false"} <= set(build)
    assert not any(a.startswith("--provenance=mode") for a in build)


def test_provenance_mode_min(env):
    result = _run(env, PROVENANCE="mode=min")
    assert result.returncode == 0, result.stderr
    assert {"--provenance=mode=min", "--sbom=true"} <= set(_build(env))


def test_expires_after_is_a_label_only(env):
    result = _run(env, EXPIRES_AFTER="90d")
    assert result.returncode == 0, result.stderr
    build = _build(env)
    assert "quay.expires-after=90d" in _pairs(build, "--label")
    assert not any("expires" in a for a in _pairs(build, "--annotation"))


def test_created_defaults_to_now(env):
    env = {k: v for k, v in env.items() if k != "CREATED"}
    result = _run(env)
    assert result.returncode == 0, result.stderr
    created = [
        label for label in _pairs(_build(env), "--label")
        if label.startswith("org.opencontainers.image.created=")
    ]
    assert len(created) == 1
    stamp = created[0].split("=", 1)[1]
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", stamp)


def test_more_labels_are_label_and_annotation(env):
    labels = (
        "org.opencontainers.image.title=my-component\n"
        "\n"
        "  org.opencontainers.image.description=Wire example component, with: a colon\n"
        "org.opencontainers.image.url=https://github.com/wireapp/my-component\n"
    )
    result = _run(env, LABELS=labels, PLATFORMS="linux/amd64,linux/arm64")
    assert result.returncode == 0, result.stderr
    build = _build(env)
    expected = [
        "org.opencontainers.image.title=my-component",
        "org.opencontainers.image.description=Wire example component, with: a colon",
        "org.opencontainers.image.url=https://github.com/wireapp/my-component",
    ]
    assert _pairs(build, "--label")[-3:] == expected
    assert _pairs(build, "--annotation")[-3:] == [f"index,manifest:{kv}" for kv in expected]
    # the stamped labels are still there, once each
    keys = [label.split("=", 1)[0] for label in _pairs(build, "--label")]
    assert len(keys) == len(set(keys))
    assert {"org.opencontainers.image.version", "org.opencontainers.image.created"} <= set(keys)


@pytest.mark.parametrize(
    "extra, message",
    [
        ({"LABELS": "not a label"}, "labels line 'not a label' is not KEY=VALUE"),
        ({"LABELS": "Title=x"}, "labels line 'Title' is not KEY=VALUE"),
        ({"LABELS": "title="}, "labels line 'title' is not KEY=VALUE"),
        ({"LABELS": "org.opencontainers.image.version=9"}, "'org.opencontainers.image.version' is set by the action"),
        ({"LABELS": "org.opencontainers.image.revision=9"}, "'org.opencontainers.image.revision' is set by the action"),
        ({"LABELS": "org.opencontainers.image.source=x"}, "'org.opencontainers.image.source' is set by the action"),
        ({"LABELS": "org.opencontainers.image.created=x"}, "'org.opencontainers.image.created' is set by the action"),
        ({"LABELS": "quay.expires-after=1d"}, "'quay.expires-after' is set by the action"),
        ({"CREATED": "yesterday"}, "CREATED must be"),
        ({"EXPIRES_AFTER": "3 months"}, "EXPIRES_AFTER must be"),
        ({"BUILD_ARGS": "not an arg"}, "is not KEY=VALUE"),
        ({"BUILD_CONTEXTS": "bundle"}, "is not name=path"),
        ({"IMAGE": "my-component"}, "is not an image repository"),
        ({"TAG": "bad tag"}, "is not a valid image tag"),
        ({"DOCKERFILE": "/nonexistent/Dockerfile"}, "does not exist"),
        ({"CONTEXT": "/nonexistent"}, "is not a directory"),
        ({"REVISION": "abc"}, "is not a full commit SHA"),
        ({"PLATFORMS": "linux/amd64, linux/arm64"}, "is not a comma-separated list"),
        ({"PROVENANCE": "max"}, "PROVENANCE must be"),
        ({"SBOM": "yes"}, "SBOM must be"),
    ],
)
def test_bad_input_fails_before_any_call(env, extra, message):
    result = _run(env, **extra)
    assert result.returncode == 1
    assert message in result.stderr
    assert _calls(env) == []
    assert Path(env["GITHUB_OUTPUT"]).read_text() == ""


def test_registry_digest_must_match_the_build(env):
    result = _run(env, FAKE_BUILT_DIGEST="sha256:" + "2" * 64)
    assert result.returncode == 1
    assert "the build pushed sha256:2" in result.stderr
    assert Path(env["GITHUB_OUTPUT"]).read_text() == ""


def test_missing_digest_fails(env):
    result = _run(env, FAKE_PRESENT="1", FAKE_REGISTRY_DIGEST="sha256:short")
    assert result.returncode == 1
    assert "::error::no digest for" in result.stderr
