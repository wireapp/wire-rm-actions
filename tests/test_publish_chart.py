"""scripts/publish-chart.sh against a fake helm first on PATH."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/publish-chart.sh"
VERSION = "4.24.3-20261005135125.gabcdef0"

# Records each call as one line, then answers like helm would. FAKE_PUBLISHED=1
# makes the version already in the registry; FAKE_PUSH_DIGEST is the digest
# the push prints (none when empty). The first FAKE_PUSH_FAILURES pushes fail
# like a Quay 500; with FAKE_FAILED_PUSH_LANDS=1 the failed push has
# committed, so the version is in the registry afterwards.
FAKE_HELM = r"""#!/usr/bin/env bash
set -euo pipefail
echo "$*" >>"$HELM_LOG"
case "$1 ${2:-}" in
"show chart")
  if [[ -f $3 ]]; then
    tar -xzOf "$3" "$(tar -tzf "$3" | grep '/Chart.yaml$' | head -n1)"
  else
    cat "$3/Chart.yaml"
  fi
  ;;
"pull "*)
  if [[ ${FAKE_PUBLISHED:-} == 1 || -f $HELM_LOG.landed ]]; then
    if [[ -n ${FAKE_EXISTING_TGZ:-} ]]; then
      mkdir -p "$6"
      cp "$FAKE_EXISTING_TGZ" "$6/"
    fi
    echo "Pulled: $2:$4"
    echo "Digest: sha256:existing"
  else
    echo "Error: $2:$4: not found" >&2
    exit 1
  fi
  ;;
"dependency build")
  echo "Saving 1 charts"
  ;;
"env HELM_REGISTRY_CONFIG")
  echo /home/runner/.config/helm/registry/config.json
  ;;
"package "*)
  name=$(sed -n 's/^name: *//p' "$2/Chart.yaml")
  out=${!#}
  touch "$out/$name-$4.tgz"
  echo "Successfully packaged chart and saved it to: $out/$name-$4.tgz"
  ;;
"push "*)
  [[ -f $2 ]] || { echo "Error: no such file $2" >&2; exit 1; }
  echo x >>"$HELM_LOG.pushes"
  if (( $(wc -l <"$HELM_LOG.pushes") <= ${FAKE_PUSH_FAILURES:-0} )); then
    [[ ${FAKE_FAILED_PUSH_LANDS:-} != 1 ]] || touch "$HELM_LOG.landed"
    echo "Error: failed to push: 500 Internal Server Error" >&2
    exit 1
  fi
  echo "Pushed: ${3#oci://}/$(basename "$2" .tgz)"
  if [[ -n ${FAKE_PUSH_DIGEST:-} ]]; then
    echo "Digest: $FAKE_PUSH_DIGEST"
  fi
  ;;
*)
  echo "fake helm: unexpected call: $*" >&2
  exit 2
  ;;
esac
"""


# The manifest helm pushed; `manifest push` keeps the file it is given.
FAKE_ORAS = r"""#!/usr/bin/env bash
set -euo pipefail
echo "oras $*" >>"$HELM_LOG"
case "$1 $2" in
"manifest fetch")
  printf '%s' '{"schemaVersion":2,"mediaType":"application/vnd.oci.image.manifest.v1+json","config":{"digest":"sha256:c"},"layers":[{"digest":"sha256:l"}],"annotations":{"org.opencontainers.image.created":"2026-10-09T00:00:00Z"}}'
  ;;
"manifest push")
  cp "${!#}" "$ORAS_PUSHED"
  echo "Pushed ${*: -2:1}"
  ;;
*)
  echo "fake oras: unexpected call: $*" >&2
  exit 2
  ;;
esac
"""


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    helm = bin_dir / "helm"
    helm.write_text(FAKE_HELM)
    helm.chmod(0o755)
    oras = bin_dir / "oras"
    oras.write_text(FAKE_ORAS)
    oras.chmod(0o755)
    chart = tmp_path / "chart"
    chart.mkdir()
    (chart / "Chart.yaml").write_text("apiVersion: v2\nname: my-component\nversion: 0.0.0\n")
    output = tmp_path / "github-output"
    output.touch()
    clean = {k: v for k, v in os.environ.items() if not k.startswith("GITHUB_")}
    return {
        **clean,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "HELM_LOG": str(tmp_path / "helm.log"),
        "GITHUB_OUTPUT": str(output),
        "CHART_PATH": str(chart),
        "VERSION": VERSION,
        "FAKE_PUSH_DIGEST": "sha256:pushed",
        "RETRY_DELAY": "0",
        "ORAS_PUSHED": str(tmp_path / "pushed-manifest.json"),
    }


def _run(env: dict[str, str], **extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT)], env={**env, **extra}, capture_output=True, text=True
    )


def _calls(env: dict[str, str]) -> list[str]:
    log = Path(env["HELM_LOG"])
    return log.read_text().splitlines() if log.exists() else []


def _chart_file(tmp_path: Path, name: str, version: str, app_version: str | None = None, filename: str | None = None) -> Path:
    """A packaged chart: <name>/Chart.yaml in a .tgz named like helm does."""
    src = tmp_path / "src" / name
    src.mkdir(parents=True, exist_ok=True)
    (src / "Chart.yaml").write_text(
        f"apiVersion: v2\nname: {name}\nversion: {version}\nappVersion: {app_version or version}\n"
    )
    tgz = tmp_path / (filename or f"{name}-{version}.tgz")
    subprocess.run(["tar", "-czf", str(tgz), "-C", str(src.parent), name], check=True)
    return tgz


def _outputs(env: dict[str, str]) -> dict[str, str]:
    lines = Path(env["GITHUB_OUTPUT"]).read_text().splitlines()
    return dict(line.split("=", 1) for line in lines)


def test_new_version_is_packaged_and_pushed(env):
    result = _run(env, REGISTRY="registry.example.com", CHANNEL="stable")
    assert result.returncode == 0, result.stderr
    calls = _calls(env)
    base = "oci://registry.example.com/wire/charts/stable"
    package = next(c for c in calls if c.startswith("package "))
    assert f"--version {VERSION} --app-version {VERSION}" in package
    push = next(c for c in calls if c.startswith("push "))
    assert push.endswith(f"/my-component-{VERSION}.tgz {base}")
    assert not any(c.startswith("dependency ") for c in calls)
    expected = {"repository": f"{base}/my-component", "digest": "sha256:pushed", "status": "pushed"}
    assert _outputs(env) == expected
    assert f"repository={base}/my-component" in result.stdout.splitlines()
    assert "digest=sha256:pushed" in result.stdout.splitlines()


def test_defaults_to_quay_dev(env):
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert _outputs(env)["repository"] == "oci://quay.io/wire/charts/dev/my-component"


def test_published_version_is_not_overwritten(env):
    result = _run(env, FAKE_PUBLISHED="1")
    assert result.returncode == 0, result.stderr
    calls = _calls(env)
    assert not any(c.startswith(("package ", "push ")) for c in calls)
    assert "already published, not overwritten" in result.stdout
    assert _outputs(env)["digest"] == "sha256:existing"


def test_dependencies_are_built(env):
    chart_yaml = Path(env["CHART_PATH"]) / "Chart.yaml"
    chart_yaml.write_text(
        chart_yaml.read_text()
        + "dependencies:\n  - name: redis\n    version: 1.0.0\n    repository: oci://registry.example.com/charts\n"
    )
    result = _run(env)
    assert result.returncode == 0, result.stderr
    calls = _calls(env)
    build = calls.index(f"dependency build {env['CHART_PATH']}")
    assert build < next(i for i, c in enumerate(calls) if c.startswith("package "))


def test_chart_name_input_wins(env):
    chart_yaml = Path(env["CHART_PATH"]) / "Chart.yaml"
    chart_yaml.write_text(chart_yaml.read_text().replace("my-component", "renamed"))
    result = _run(env, CHART_NAME="renamed")
    assert result.returncode == 0, result.stderr
    assert not any(c.startswith("show ") for c in _calls(env))
    assert _outputs(env)["repository"].endswith("/renamed")


def test_push_without_digest_fails(env):
    result = _run(env, FAKE_PUSH_DIGEST="")
    assert result.returncode == 1
    assert "::error::no digest for" in result.stderr
    assert Path(env["GITHUB_OUTPUT"]).read_text() == ""


def test_unknown_chart_name_fails(env):
    (Path(env["CHART_PATH"]) / "Chart.yaml").write_text("apiVersion: v2\nversion: 0.0.0\n")
    result = _run(env)
    assert result.returncode == 1
    assert "::error::cannot read the chart name" in result.stderr
    assert not any(c.startswith(("pull ", "package ", "push ")) for c in _calls(env))


def test_expires_after_annotates_the_pushed_manifest(env):
    result = _run(env, EXPIRES_AFTER="90d")
    assert result.returncode == 0, result.stderr
    target = f"quay.io/wire/charts/dev/my-component:{VERSION}"
    config = "--registry-config /home/runner/.config/helm/registry/config.json"
    oras = [c for c in _calls(env) if c.startswith("oras ")]
    assert oras == [
        f"oras manifest fetch {config} {target}",
        f"oras manifest push {config} --media-type application/vnd.oci.image.manifest.v1+json {target} "
        + oras[1].rsplit(" ", 1)[1],
    ]
    pushed = Path(env["ORAS_PUSHED"]).read_bytes()
    manifest = json.loads(pushed)
    assert manifest["annotations"] == {
        "org.opencontainers.image.created": "2026-10-09T00:00:00Z",
        "quay.expires-after": "90d",
    }
    assert manifest["layers"] == [{"digest": "sha256:l"}]
    digest = "sha256:" + hashlib.sha256(pushed).hexdigest()
    assert _outputs(env)["digest"] == digest
    assert f"expires after 90d ({digest})" in result.stdout


def test_no_expiry_by_default(env):
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert not any(c.startswith("oras ") for c in _calls(env))
    assert _outputs(env)["digest"] == "sha256:pushed"


def test_published_version_is_not_annotated_again(env):
    result = _run(env, FAKE_PUBLISHED="1", EXPIRES_AFTER="90d")
    assert result.returncode == 0, result.stderr
    assert not any(c.startswith(("oras ", "push ")) for c in _calls(env))
    assert _outputs(env)["digest"] == "sha256:existing"


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"EXPIRES_AFTER": "90"}, "EXPIRES_AFTER must be a number of hours, days or weeks"),
        ({"EXPIRES_AFTER": "0d"}, "EXPIRES_AFTER must be a number of hours, days or weeks"),
        ({"EXPIRES_AFTER": "90d; rm -rf /"}, "EXPIRES_AFTER must be a number of hours, days or weeks"),
        ({"EXPIRES_AFTER": "90d", "CHANNEL": "stable"}, "EXPIRES_AFTER is for the dev channel only"),
    ],
)
def test_expires_after_is_checked_before_any_registry_call(env, extra, message):
    result = _run(env, **extra)
    assert result.returncode == 1
    assert message in result.stderr
    assert _calls(env) == []


def test_chart_file_is_pushed_as_is(env, tmp_path):
    tgz = _chart_file(tmp_path, "my-component", "1.41.5")
    result = _run(env, CHART_PATH="", VERSION="", CHART_FILE=str(tgz), CHANNEL="stable")
    assert result.returncode == 0, result.stderr
    calls = _calls(env)
    assert not any(c.startswith(("package ", "dependency ")) for c in calls)
    assert f"push {tgz} oci://quay.io/wire/charts/stable" in calls
    assert _outputs(env) == {
        "repository": "oci://quay.io/wire/charts/stable/my-component",
        "digest": "sha256:pushed",
        "status": "pushed",
    }


def test_chart_file_already_published_with_the_same_content_is_present(env, tmp_path):
    tgz = _chart_file(tmp_path, "my-component", "1.41.5")
    result = _run(env, CHART_PATH="", VERSION="", CHART_FILE=str(tgz), FAKE_PUBLISHED="1", FAKE_EXISTING_TGZ=str(tgz))
    assert result.returncode == 0, result.stderr
    assert not any(c.startswith("push ") for c in _calls(env))
    assert "already published with the same chart" in result.stdout
    assert _outputs(env)["status"] == "present"
    assert _outputs(env)["digest"] == "sha256:existing"


def test_chart_file_already_published_with_another_content_fails(env, tmp_path):
    tgz = _chart_file(tmp_path, "my-component", "1.41.5")
    other = _chart_file(tmp_path / "other", "my-component", "1.41.5")
    (tmp_path / "other" / "src" / "my-component" / "values.yaml").write_text("a: 1\n")
    subprocess.run(["tar", "-czf", str(other), "-C", str(tmp_path / "other" / "src"), "my-component"], check=True)
    result = _run(env, CHART_PATH="", VERSION="", CHART_FILE=str(tgz), FAKE_PUBLISHED="1", FAKE_EXISTING_TGZ=str(other))
    assert result.returncode == 1
    assert "already published with another content" in result.stderr
    assert not any(c.startswith("push ") for c in _calls(env))
    assert Path(env["GITHUB_OUTPUT"]).read_text() == ""


def test_chart_file_version_is_checked(env, tmp_path):
    tgz = _chart_file(tmp_path, "my-component", "1.41.5")
    result = _run(env, CHART_PATH="", CHART_FILE=str(tgz), VERSION="1.41.6")
    assert result.returncode == 1
    assert "is version '1.41.5', expected '1.41.6'" in result.stderr
    assert not any(c.startswith(("pull ", "push ")) for c in _calls(env))


def test_chart_file_app_version_must_match(env, tmp_path):
    tgz = _chart_file(tmp_path, "my-component", "1.41.5", app_version="1.41.4")
    result = _run(env, CHART_PATH="", VERSION="", CHART_FILE=str(tgz))
    assert result.returncode == 1
    assert "has appVersion '1.41.4', expected the chart version '1.41.5'" in result.stderr


def test_chart_file_name_must_follow_helm(env, tmp_path):
    tgz = _chart_file(tmp_path, "my-component", "1.41.5", filename="chart.tgz")
    result = _run(env, CHART_PATH="", VERSION="", CHART_FILE=str(tgz))
    assert result.returncode == 1
    assert "should be named my-component-1.41.5.tgz" in result.stderr


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"CHART_PATH": ""}, "CHART_PATH or CHART_FILE is required"),
        ({"CHART_FILE": "x.tgz"}, "CHART_PATH and CHART_FILE are exclusive"),
        ({"CHART_PATH": "", "CHART_FILE": "x.tgz", "EXPIRES_AFTER": "90d"}, "EXPIRES_AFTER is refused with CHART_FILE"),
        ({"CHART_PATH": "", "CHART_FILE": "missing.tgz"}, "CHART_FILE 'missing.tgz' not found"),
    ],
)
def test_chart_file_inputs_are_checked_before_any_registry_call(env, extra, message):
    result = _run(env, **extra)
    assert result.returncode == 1
    assert message in result.stderr
    assert _calls(env) == []


def _pushes(env: dict[str, str]) -> list[str]:
    return [c for c in _calls(env) if c.startswith("push ")]


def test_no_retry_by_default(env, tmp_path):
    tgz = _chart_file(tmp_path, "my-component", "1.41.5")
    result = _run(env, CHART_PATH="", VERSION="", CHART_FILE=str(tgz), FAKE_PUSH_FAILURES="1")
    assert result.returncode == 1
    assert "failed after 1 attempt(s)" in result.stderr
    assert len(_pushes(env)) == 1
    assert Path(env["GITHUB_OUTPUT"]).read_text() == ""


def test_failed_push_is_tried_again(env, tmp_path):
    tgz = _chart_file(tmp_path, "my-component", "1.41.5")
    result = _run(env, CHART_PATH="", VERSION="", CHART_FILE=str(tgz), ATTEMPTS="3", FAKE_PUSH_FAILURES="2")
    assert result.returncode == 0, result.stderr
    assert len(_pushes(env)) == 3
    assert "attempt 1/3" in result.stdout and "attempt 2/3" in result.stdout
    assert _outputs(env)["status"] == "pushed"
    assert _outputs(env)["digest"] == "sha256:pushed"


def test_presence_is_checked_before_every_attempt(env, tmp_path):
    tgz = _chart_file(tmp_path, "my-component", "1.41.5")
    _run(env, CHART_PATH="", VERSION="", CHART_FILE=str(tgz), ATTEMPTS="3", FAKE_PUSH_FAILURES="2")
    kinds = [c.split()[0] for c in _calls(env) if c.startswith(("pull ", "push "))]
    assert kinds == ["pull", "push", "pull", "push", "pull", "push"]


def test_failed_push_that_landed_is_present_not_pushed_again(env, tmp_path):
    tgz = _chart_file(tmp_path, "my-component", "1.41.5")
    result = _run(
        env, CHART_PATH="", VERSION="", CHART_FILE=str(tgz), ATTEMPTS="3",
        FAKE_PUSH_FAILURES="1", FAKE_FAILED_PUSH_LANDS="1", FAKE_EXISTING_TGZ=str(tgz),
    )
    assert result.returncode == 0, result.stderr
    assert len(_pushes(env)) == 1
    assert _outputs(env)["status"] == "present"
    assert _outputs(env)["digest"] == "sha256:existing"


def test_failed_push_that_landed_with_another_content_fails(env, tmp_path):
    tgz = _chart_file(tmp_path, "my-component", "1.41.5")
    other = _chart_file(tmp_path / "other", "my-component", "1.41.5")
    (tmp_path / "other" / "src" / "my-component" / "values.yaml").write_text("a: 1\n")
    subprocess.run(["tar", "-czf", str(other), "-C", str(tmp_path / "other" / "src"), "my-component"], check=True)
    result = _run(
        env, CHART_PATH="", VERSION="", CHART_FILE=str(tgz), ATTEMPTS="3",
        FAKE_PUSH_FAILURES="1", FAKE_FAILED_PUSH_LANDS="1", FAKE_EXISTING_TGZ=str(other),
    )
    assert result.returncode == 1
    assert "already published with another content" in result.stderr
    assert len(_pushes(env)) == 1


def test_gives_up_after_the_last_attempt(env, tmp_path):
    tgz = _chart_file(tmp_path, "my-component", "1.41.5")
    result = _run(env, CHART_PATH="", VERSION="", CHART_FILE=str(tgz), ATTEMPTS="2", FAKE_PUSH_FAILURES="5")
    assert result.returncode == 1
    assert "failed after 2 attempt(s)" in result.stderr
    assert len(_pushes(env)) == 2
    assert Path(env["GITHUB_OUTPUT"]).read_text() == ""


@pytest.mark.parametrize(
    "extra, message",
    [
        ({"ATTEMPTS": "0"}, "ATTEMPTS must be a positive number"),
        ({"ATTEMPTS": "two"}, "ATTEMPTS must be a positive number"),
        ({"ATTEMPTS": "2"}, "ATTEMPTS is for CHART_FILE only"),
        ({"RETRY_DELAY": "soon"}, "RETRY_DELAY must be a number of seconds"),
    ],
)
def test_attempts_are_checked_before_any_registry_call(env, extra, message):
    result = _run(env, **extra)
    assert result.returncode == 1
    assert message in result.stderr
    assert _calls(env) == []
