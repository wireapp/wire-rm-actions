"""scripts/quay-login.sh against a fake GitHub token endpoint, a fake Quay
federation endpoint and a fake docker first on PATH."""

from __future__ import annotations

import base64
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/quay-login.sh"
def _segment(part: bytes) -> str:
    return base64.urlsafe_b64encode(part).rstrip(b"=").decode()


# A JWT-shaped token, assembled here so that no token literal sits in the tree.
OIDC = ".".join(_segment(part) for part in (b'{"alg":"RS256"}', b'{"aud":"quay"}', b"signature"))
ROBOT_TOKEN = "robot-token-with-\"quote\"-and-\\backslash"


class FakeEndpoint:
    """Answers every request with ``status`` and ``body``, records the calls."""

    def __init__(self, status: int = 200, body: bytes = b"{}"):
        self.status = status
        self.body = body
        self.calls: list[dict] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self):
                fake.calls.append(
                    {
                        "method": self.command,
                        "path": self.path,
                        "query": parse_qs(urlparse(self.path).query),
                        "auth": self.headers.get("Authorization", ""),
                    }
                )
                self.send_response(fake.status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(fake.body)

            do_GET = _answer  # noqa: N815
            do_POST = _answer  # noqa: N815

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.fixture
def idp():
    fake = FakeEndpoint(body=('{"value": "%s"}' % OIDC).encode())
    yield fake
    fake.close()


@pytest.fixture
def quay():
    fake = FakeEndpoint(body=('{"token": %s}' % _json_string(ROBOT_TOKEN)).encode())
    yield fake
    fake.close()


def _json_string(value: str) -> str:
    import json

    return json.dumps(value)


@pytest.fixture
def fake_docker(tmp_path: Path) -> tuple[str, Path]:
    """A PATH whose docker logs its arguments and its stdin to the returned file."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "docker.log"
    fake = bin_dir / "docker"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "args: %s\\n" "$*" >>"{log}"\n'
        f'printf "stdin: %s\\n" "$(cat)" >>"{log}"\n'
        'echo "Login Succeeded"\n'
    )
    fake.chmod(0o755)
    return f"{bin_dir}{os.pathsep}{os.environ['PATH']}", log


def _run(idp, quay, fake_docker, **env: str) -> subprocess.CompletedProcess:
    clean = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("ACTIONS_", "GITHUB_")) and k not in {"ROBOT", "REGISTRY", "AUDIENCE", "DOCKER_LOGIN", "FEDERATION_URL"}
    }
    path, _ = fake_docker
    base = {
        "ROBOT": "wire+gha_my-component",
        "FEDERATION_URL": quay.url + "/oauth2/federation/robot/token",
        "ACTIONS_ID_TOKEN_REQUEST_URL": idp.url + "/token?api-version=2.0",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "runner-request-token",
        "PATH": path,
    }
    return subprocess.run(
        ["bash", str(SCRIPT)], env={**clean, **base, **env}, capture_output=True, text=True
    )


def test_exchanges_the_oidc_token_and_logs_docker_in(idp, quay, fake_docker, tmp_path):
    out = tmp_path / "output"
    result = _run(idp, quay, fake_docker, GITHUB_OUTPUT=str(out))
    assert result.returncode == 0, result.stderr
    # The OIDC token is requested for the audience quay with the runner's request token.
    assert idp.calls[0]["query"]["audience"] == ["quay"]
    assert idp.calls[0]["auth"] == "Bearer runner-request-token"
    # The exchange is basic auth robot:oidc-token.
    expected = base64.b64encode(f"wire+gha_my-component:{OIDC}".encode()).decode()
    assert quay.calls[0]["auth"] == f"Basic {expected}"
    # docker login gets the robot token on stdin, never on its command line.
    _, log = fake_docker
    text = log.read_text()
    assert "args: login quay.io --username wire+gha_my-component --password-stdin\n" in text
    assert f"stdin: {ROBOT_TOKEN}\n" in text
    assert out.read_text() == f"token={ROBOT_TOKEN}\n"


def test_both_tokens_are_masked_first_and_never_printed(idp, quay, fake_docker):
    result = _run(idp, quay, fake_docker)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == f"::add-mask::{OIDC}"
    assert lines[1] == f"::add-mask::{ROBOT_TOKEN}"
    rest = "\n".join(lines[2:]) + result.stderr
    assert OIDC not in rest
    assert ROBOT_TOKEN not in rest
    assert "runner-request-token" not in result.stdout + result.stderr


def test_docker_login_can_be_skipped(idp, quay, fake_docker):
    result = _run(idp, quay, fake_docker, DOCKER_LOGIN="false")
    assert result.returncode == 0, result.stderr
    _, log = fake_docker
    assert not log.exists()
    assert "Robot token for quay.io as wire+gha_my-component" in result.stdout


def test_registry_and_audience_are_passed_on(idp, quay, fake_docker):
    result = _run(idp, quay, fake_docker, REGISTRY="registry.example.com", AUDIENCE="my-quay")
    assert result.returncode == 0, result.stderr
    assert idp.calls[0]["query"]["audience"] == ["my-quay"]
    _, log = fake_docker
    assert "args: login registry.example.com --username" in log.read_text()


@pytest.mark.parametrize(
    "robot",
    ["wire+gha-my-component; rm -rf /", "wire", "wire+", "+gha_my-component", "Wire+gha_my-component", "wire+gha__my-component", "wire+gha_my-component-",
     "wire+-gha", "wire+gha my-component", 'wire+gha"my-component', "wire+gha\\my-component", "wire+gha_my-component\nuser = x"],
)
def test_a_robot_that_is_not_org_plus_name_is_refused(idp, quay, fake_docker, robot: str):
    result = _run(idp, quay, fake_docker, ROBOT=robot)
    assert result.returncode == 1
    assert "::error::ROBOT must be <organization>+<name>" in result.stderr
    assert idp.calls == []


@pytest.mark.parametrize("robot", ["wire+gha_my-component", "wire+gha_wire-server", "my-org+ci.robot", "wire+gha_my-component"])
def test_quay_names_with_hyphens_and_dots_are_accepted(idp, quay, fake_docker, robot: str):
    result = _run(idp, quay, fake_docker, ROBOT=robot)
    assert result.returncode == 0, result.stderr
    assert f"--username {robot} --password-stdin" in fake_docker[1].read_text()


def test_without_id_token_permission_it_is_an_error(idp, quay, fake_docker):
    result = _run(idp, quay, fake_docker, ACTIONS_ID_TOKEN_REQUEST_URL="", ACTIONS_ID_TOKEN_REQUEST_TOKEN="")
    assert result.returncode == 1
    assert "permissions: id-token: write" in result.stderr


def test_a_refused_exchange_is_an_error_with_a_filtered_reason(idp, fake_docker):
    quay = FakeEndpoint(status=401, body=b'{"error": "invalid_grant", "error_description": "subject <b>mismatch</b>\\n$(evil)"}')
    try:
        result = _run(idp, quay, fake_docker)
    finally:
        quay.close()
    assert result.returncode == 1
    assert "refused the federation exchange for wire+gha_my-component (HTTP 401, subject bmismatch/b(evil))" in result.stderr
    assert "$(" not in result.stderr and "<b>" not in result.stderr
    _, log = fake_docker
    assert not log.exists()


def test_a_token_that_is_not_a_jwt_is_refused(quay, fake_docker):
    idp = FakeEndpoint(body=b'{"value": "::add-mask::x\\nnot a jwt"}')
    try:
        result = _run(idp, quay, fake_docker)
    finally:
        idp.close()
    assert result.returncode == 1
    assert "no OIDC token for audience quay" in result.stderr
    assert quay.calls == []


def test_the_federation_url_must_be_https(idp, quay, fake_docker):
    result = _run(idp, quay, fake_docker, FEDERATION_URL="http://quay.example.com/oauth2/federation/robot/token")
    assert result.returncode == 1
    assert "FEDERATION_URL must be https://" in result.stderr
    assert idp.calls == []
