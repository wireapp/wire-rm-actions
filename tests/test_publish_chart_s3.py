"""scripts/publish-chart-s3.sh against a fake helm first on PATH."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/publish-chart-s3.sh"

# Records each call as one line, then answers like helm would. FAKE_PLUGIN=1
# means helm-s3 is installed; FAKE_EXISTING_TGZ is the package already in the
# repository under its version (absent when empty).
FAKE_HELM = r"""#!/usr/bin/env bash
set -euo pipefail
echo "$*" >>"$HELM_LOG"
case "$1 ${2:-}" in
"show chart")
  tar -xzOf "$3" "$(tar -tzf "$3" | grep '/Chart.yaml$' | head -n1)"
  ;;
"plugin list")
  echo "NAME VERSION DESCRIPTION"
  [[ ${FAKE_PLUGIN:-} != 1 ]] || echo "s3 0.15.1 S3 plugin"
  ;;
"plugin install")
  ;;
"repo add"|"repo update")
  ;;
"search repo")
  if [[ -n ${FAKE_EXISTING_TGZ:-} ]]; then
    printf '[{"name":"%s","version":"%s"}]\n' "$3" "$5"
  else
    echo "[]"
  fi
  ;;
"pull "*)
  cp "$FAKE_EXISTING_TGZ" "${!#}/"
  ;;
"s3 push")
  echo "pushed $4 $5" >>"$HELM_LOG.pushes"
  ;;
*)
  echo "fake helm: unexpected call: $*" >&2
  exit 2
  ;;
esac
"""


def _chart(tmp_path: Path, name: str, version: str, filename: str | None = None, extra: str = "") -> Path:
    src = tmp_path / "src" / name
    src.mkdir(parents=True, exist_ok=True)
    (src / "Chart.yaml").write_text(f"apiVersion: v2\nname: {name}\nversion: {version}\nappVersion: {version}\n{extra}")
    tgz = tmp_path / (filename or f"{name}-{version}.tgz")
    subprocess.run(["tar", "-czf", str(tgz), "-C", str(src.parent), name], check=True)
    return tgz


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    helm = bin_dir / "helm"
    helm.write_text(FAKE_HELM)
    helm.chmod(0o755)
    output = tmp_path / "github-output"
    output.touch()
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("GITHUB_", "AWS_"))}
    return {
        **clean,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "HELM_LOG": str(tmp_path / "helm.log"),
        "GITHUB_OUTPUT": str(output),
        "CHART_FILE": str(_chart(tmp_path, "my-component", "2.0.17-alpha.1")),
        "S3_REPOSITORY": "charts-develop",
        "AWS_ACCESS_KEY_ID": "id",
        "AWS_SECRET_ACCESS_KEY": "secret",
        "FAKE_PLUGIN": "1",
    }


def _run(env: dict[str, str], **extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT)], env={**env, **extra}, capture_output=True, text=True)


def _calls(env: dict[str, str]) -> list[str]:
    log = Path(env["HELM_LOG"])
    return log.read_text().splitlines() if log.exists() else []


def _pushes(env: dict[str, str]) -> list[str]:
    log = Path(env["HELM_LOG"] + ".pushes")
    return log.read_text().splitlines() if log.exists() else []


def _outputs(env: dict[str, str]) -> dict[str, str]:
    lines = Path(env["GITHUB_OUTPUT"]).read_text().splitlines()
    return dict(line.split("=", 1) for line in lines)


def test_pushes_a_new_version(env):
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert _pushes(env) == [f"pushed {env['CHART_FILE']} charts-develop"]
    assert "repo add charts-develop s3://public.wire.com/charts-develop" in _calls(env)
    assert _outputs(env) == {
        "name": "my-component",
        "version": "2.0.17-alpha.1",
        "repository": "s3://public.wire.com/charts-develop",
        "status": "pushed",
    }


def test_never_forces_the_push(env):
    assert _run(env).returncode == 0
    assert not any("--force" in call for call in _calls(env))
    assert any(call.startswith("s3 push --relative ") for call in _calls(env))


def test_the_same_package_is_a_no_op(env):
    result = _run(env, FAKE_EXISTING_TGZ=env["CHART_FILE"])
    assert result.returncode == 0, result.stderr
    assert _pushes(env) == []
    assert _outputs(env)["status"] == "present"


def test_another_content_under_the_version_fails(env, tmp_path):
    other = _chart(tmp_path / "other", "my-component", "2.0.17-alpha.1", extra="description: other\n")
    result = _run(env, FAKE_EXISTING_TGZ=str(other))
    assert result.returncode == 1
    assert "refusing to overwrite" in result.stderr
    assert _pushes(env) == []


def test_installs_the_plugin_when_missing(env):
    assert _run(env, FAKE_PLUGIN="0", HELM_S3_VERSION="0.16.0").returncode == 0
    assert "plugin install https://github.com/hypnoglow/helm-s3.git --version 0.16.0" in _calls(env)


def test_keeps_an_installed_plugin(env):
    assert _run(env).returncode == 0
    assert not any(call.startswith("plugin install") for call in _calls(env))


def test_an_explicit_url_is_used(env):
    assert _run(env, S3_REPOSITORY="charts-extra", S3_URL="s3://example-bucket/charts").returncode == 0
    assert "repo add charts-extra s3://example-bucket/charts" in _calls(env)
    assert _outputs(env)["repository"] == "s3://example-bucket/charts"


def test_a_package_named_unlike_its_chart_fails(env, tmp_path):
    misnamed = _chart(tmp_path / "misnamed", "my-component", "2.0.17-alpha.1", filename="my-component.tgz")
    result = _run(env, CHART_FILE=str(misnamed))
    assert result.returncode == 1
    assert "should be named my-component-2.0.17-alpha.1.tgz" in result.stderr
    assert _pushes(env) == []


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"CHART_FILE": "/nonexistent/my-component-1.0.0.tgz"}, "not found"),
        ({"S3_REPOSITORY": ""}, "s3-repository"),
        ({"S3_REPOSITORY": "Bad_Name"}, "s3-repository"),
        ({"S3_URL": "https://public.wire.com/x"}, "s3-url"),
        ({"AWS_ACCESS_KEY_ID": ""}, "AWS credentials"),
        ({"AWS_SECRET_ACCESS_KEY": ""}, "AWS credentials"),
    ],
)
def test_invalid_inputs_fail_before_any_helm_call(env, override, message):
    result = _run(env, **override)
    assert result.returncode == 1
    assert message in result.stderr
    assert _calls(env) == []
