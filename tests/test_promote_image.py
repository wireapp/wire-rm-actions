"""scripts/promote-image.sh against a fake crane first on PATH."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/promote-image.sh"
DIGEST = "sha256:" + "a" * 64
OTHER = "sha256:" + "b" * 64
REPOSITORY = "quay.io/wire/my-component"

# Records each call, then answers from a one-line "tag store" file: the tag
# <TAG> resolves to the digest written in $FAKE_TAG_FILE; FAKE_CANDIDATE=0
# makes the candidate manifest missing.
FAKE_CRANE = r"""#!/usr/bin/env bash
set -euo pipefail
echo "crane $*" >>"$CRANE_LOG"
case "$1" in
auth)
  if [[ $2 == login ]]; then
    read -r password || true
    echo "login $3 as $5 with ${#password} chars" >>"$CRANE_LOG"
  fi
  ;;
manifest)
  [[ ${FAKE_CANDIDATE:-1} == 1 ]] || { echo "MANIFEST_UNKNOWN" >&2; exit 1; }
  echo '{"schemaVersion":2}'
  ;;
digest)
  [[ -s $FAKE_TAG_FILE ]] || { echo "MANIFEST_UNKNOWN" >&2; exit 1; }
  cat "$FAKE_TAG_FILE"
  ;;
tag)
  printf '%s' "${2#*@}" >"$FAKE_TAG_FILE"
  ;;
*)
  echo "fake crane: unexpected call: $*" >&2
  exit 2
  ;;
esac
"""


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    crane = bin_dir / "crane"
    crane.write_text(FAKE_CRANE)
    crane.chmod(0o755)
    output = tmp_path / "github-output"
    output.touch()
    (tmp_path / "tag").touch()
    clean = {k: v for k, v in os.environ.items() if not k.startswith("GITHUB_")}
    return {
        **clean,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "CRANE_LOG": str(tmp_path / "crane.log"),
        "FAKE_TAG_FILE": str(tmp_path / "tag"),
        "GITHUB_OUTPUT": str(output),
        "REPOSITORY": REPOSITORY,
        "DIGEST": DIGEST,
        "TAG": "1.41.5",
    }


def _run(env: dict[str, str], **extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT)], env={**env, **extra}, capture_output=True, text=True)


def _calls(env: dict[str, str]) -> list[str]:
    log = Path(env["CRANE_LOG"])
    return log.read_text().splitlines() if log.exists() else []


def _outputs(env: dict[str, str]) -> dict[str, str]:
    lines = Path(env["GITHUB_OUTPUT"]).read_text().splitlines()
    return dict(line.split("=", 1) for line in lines)


def test_promotes_by_digest_without_login(env):
    result = _run(env)
    assert result.returncode == 0, result.stderr
    calls = _calls(env)
    assert f"crane manifest {REPOSITORY}@{DIGEST}" in calls
    assert f"crane tag {REPOSITORY}@{DIGEST} 1.41.5" in calls
    assert not any(c.startswith("crane auth") for c in calls)
    assert _outputs(env) == {"digest": DIGEST, "status": "promoted"}


def test_logs_in_on_stdin_when_a_user_is_given(env):
    result = _run(env, REGISTRY_USER="wire+robot", REGISTRY_PASSWORD="s3cret")
    assert result.returncode == 0, result.stderr
    calls = _calls(env)
    assert "crane auth login quay.io --username wire+robot --password-stdin" in calls
    assert "login quay.io as wire+robot with 6 chars" in calls
    assert "s3cret" not in result.stdout + result.stderr


def test_already_promoted_is_present(env):
    Path(env["FAKE_TAG_FILE"]).write_text(DIGEST)
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert not any(c.startswith("crane tag") for c in _calls(env))
    assert "already promoted" in result.stdout
    assert _outputs(env) == {"digest": DIGEST, "status": "present"}


def test_release_tag_at_another_digest_fails(env):
    Path(env["FAKE_TAG_FILE"]).write_text(OTHER)
    result = _run(env)
    assert result.returncode == 1
    assert "refusing to overwrite a published image" in result.stderr
    assert not any(c.startswith("crane tag") for c in _calls(env))
    assert Path(env["GITHUB_OUTPUT"]).read_text() == ""


def test_missing_candidate_fails(env):
    result = _run(env, FAKE_CANDIDATE="0")
    assert result.returncode == 1
    assert "no longer exists in the registry" in result.stderr
    assert not any(c.startswith("crane tag") for c in _calls(env))


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"REPOSITORY": "Quay.io/wire/my-component"}, "is not an image repository"),
        ({"REPOSITORY": "my-component"}, "is not an image repository"),
        ({"DIGEST": "sha256:abc"}, "is not a sha256 digest"),
        ({"TAG": "latest"}, "is not a release version"),
        ({"TAG": "v1.41.5"}, "is not a release version"),
        ({"REGISTRY_USER": "wire+robot"}, "REGISTRY_PASSWORD is required with REGISTRY_USER"),
        ({"REGISTRY_PASSWORD": "x"}, "REGISTRY_PASSWORD is set without REGISTRY_USER"),
    ],
)
def test_inputs_are_checked_before_any_registry_call(env, extra, message):
    result = _run(env, **extra)
    assert result.returncode == 1
    assert message in result.stderr
    assert _calls(env) == []
