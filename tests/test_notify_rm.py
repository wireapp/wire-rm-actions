"""scripts/notify-rm.sh against fake release managers on localhost."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/notify-rm.sh"


class FakeRM:
    """Answers POST /api/v1/versions with ``status`` and records each call."""

    def __init__(self, status: int = 200):
        self.status = status
        self.body = b"{}"
        self.calls: list[dict] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers["Content-Length"]))
                fake.calls.append(
                    {
                        "path": self.path,
                        "auth": self.headers["Authorization"],
                        "body": json.loads(body),
                    }
                )
                self.send_response(fake.status)
                self.end_headers()
                self.wfile.write(fake.body)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.fixture
def rms():
    staging, prod = FakeRM(), FakeRM()
    yield staging, prod
    staging.close()
    prod.close()


def _run(**env: str) -> subprocess.CompletedProcess:
    clean = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("RM_", "GITHUB_")) and k != "REQUIRED"
    }
    base = {"COMPONENT": "my-component", "VERSION": "4.24.3-20261005135125.gabcdef0"}
    return subprocess.run(
        ["bash", str(SCRIPT)], env={**clean, **base, **env}, capture_output=True, text=True
    )


def test_declares_to_both(rms):
    staging, prod = rms
    result = _run(
        RM_STAGING_URL=staging.url,
        RM_STAGING_TOKEN="s-token",
        RM_PROD_URL=prod.url + "/",
        RM_PROD_TOKEN="p-token",
        DIGEST="sha256:aa",
        META="team=web",
    )
    assert result.returncode == 0, result.stderr
    assert staging.calls[0]["auth"] == "Bearer s-token"
    assert prod.calls[0]["auth"] == "Bearer p-token"
    assert prod.calls[0]["path"] == "/api/v1/versions"
    record = staging.calls[0]["body"][0]
    assert record["component_id"] == "my-component"
    assert record["source"] == "chart-release"
    assert record["digest"] == "sha256:aa"
    assert record["meta"] == {"build": "dev", "team": "web"}
    assert "repository" not in record and "release_note" not in record


def test_release_fields(rms):
    staging, _ = rms
    result = _run(
        RM_STAGING_URL=staging.url,
        RM_STAGING_TOKEN="t",
        KIND="ga",
        RELEASED_AT="2026-10-05",
        NOTE_TITLE="v4.24.3",
        NOTE_DESCRIPTION="body",
    )
    assert result.returncode == 0, result.stderr
    record = staging.calls[0]["body"][0]
    assert record["released_at"] == "2026-10-05"
    assert record["release_note"] == {"title": "v4.24.3", "description": "body"}
    assert record["meta"]["build"] == "ga"


def test_unset_url_skips_with_explicit_warning(rms):
    staging, _ = rms
    result = _run(RM_STAGING_URL=staging.url, RM_STAGING_TOKEN="t", RM_PROD_URL="", REQUIRED="true")
    assert result.returncode == 0, result.stderr
    assert len(staging.calls) == 1
    assert "release manager prod: RM_PROD_URL is not set or empty" in result.stdout


def test_failure_only_warns(rms):
    staging, prod = rms
    staging.status = 500
    result = _run(
        RM_STAGING_URL=staging.url,
        RM_STAGING_TOKEN="t",
        RM_PROD_URL=prod.url,
        RM_PROD_TOKEN="t",
    )
    assert result.returncode == 0, result.stderr
    assert "::warning::release manager staging" in result.stdout
    assert len(prod.calls) == 1


def test_response_body_shown_on_failure_only_without_workflow_commands(rms):
    staging, prod = rms
    staging.status = 500
    staging.body = b"boom\n::warning::injected\n" + b"x" * 1000
    prod.body = b"prod-body"
    result = _run(
        RM_STAGING_URL=staging.url,
        RM_STAGING_TOKEN="t",
        RM_PROD_URL=prod.url,
        RM_PROD_TOKEN="t",
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("::stop-commands::"))
    stop = lines[start].removeprefix("::stop-commands::")
    assert len(stop) == 32
    end = lines.index(f"::{stop}::")
    assert start < lines.index("::warning::injected") < end
    assert "x" * 501 not in result.stdout
    assert "prod-body" not in result.stdout


@pytest.mark.parametrize("status", [500, 302])
def test_failure_fails_when_required(rms, status):
    staging, prod = rms
    staging.status = status
    result = _run(
        RM_STAGING_URL=staging.url,
        RM_STAGING_TOKEN="t",
        RM_PROD_URL=prod.url,
        RM_PROD_TOKEN="t",
        REQUIRED="true",
    )
    assert result.returncode == 1
    assert "declaration failed on: staging" in result.stderr
    assert len(prod.calls) == 1


def test_missing_token_is_a_failure(rms):
    staging, _ = rms
    assert _run(RM_STAGING_URL=staging.url).returncode == 0
    assert _run(RM_STAGING_URL=staging.url, REQUIRED="true").returncode == 1
    assert staging.calls == []


def test_unreachable_only_warns():
    result = _run(RM_STAGING_URL="http://127.0.0.1:9", RM_STAGING_TOKEN="t")
    assert result.returncode == 0
    assert "(unreachable)" in result.stdout


@pytest.mark.parametrize(
    "url", ["https://secret-rm-host.invalid", "http://secret-rm-host.example.com", "https://secret-rm-host.invalid/path"]
)
def test_the_url_never_reaches_the_log(url):
    # The job log of a public component is public: the release managers are named rm-staging and rm-prod.
    result = _run(RM_STAGING_URL=url, RM_STAGING_TOKEN="t", RM_PROD_URL=url, RM_PROD_TOKEN="t")
    assert result.returncode == 0
    # The runner consumes ::add-mask:: lines without displaying them.
    shown = "\n".join(line for line in (result.stdout + result.stderr).splitlines() if not line.startswith("::add-mask::"))
    assert "secret-rm-host" not in shown
    assert "rm-staging" in result.stdout and "rm-prod" in result.stdout


def test_the_url_and_its_host_are_masked_before_any_request():
    result = _run(RM_STAGING_URL="https://user:pw@secret-rm-host.invalid:8443/base/", RM_STAGING_TOKEN="t")
    assert result.returncode == 0
    lines = result.stdout.splitlines()
    assert "::add-mask::https://user:pw@secret-rm-host.invalid:8443/base" in lines
    assert "::add-mask::secret-rm-host.invalid" in lines
    first_http = next(i for i, line in enumerate(lines) if line.startswith("release manager staging: HTTP"))
    assert max(i for i, line in enumerate(lines) if line.startswith("::add-mask::")) < first_http


@pytest.mark.parametrize("url", ["https://secret-rm-host.invalid\n::warning::injected", "https://secret-rm-host.invalid\r::error::injected"])
def test_a_url_with_a_control_character_is_refused(url):
    result = _run(RM_STAGING_URL=url, RM_STAGING_TOKEN="t", REQUIRED="true")
    assert result.returncode == 1
    assert "the URL holds a control character" in result.stdout
    assert "injected" not in result.stdout + result.stderr
    assert "::add-mask::" not in result.stdout


@pytest.mark.parametrize("url", ["http://example.com", "http://127.0.0.1.example.com", "ftp://127.0.0.1"])
def test_non_https_url_is_refused(rms, url):
    result = _run(RM_STAGING_URL=url, RM_STAGING_TOKEN="t")
    assert result.returncode == 0
    assert "not an https:// URL" in result.stdout
    result = _run(RM_STAGING_URL=url, RM_STAGING_TOKEN="t", REQUIRED="true")
    assert result.returncode == 1
    assert "declaration failed on: staging" in result.stderr


def test_loopback_http_is_accepted(rms):
    staging, prod = rms
    result = _run(
        RM_STAGING_URL=staging.url,
        RM_STAGING_TOKEN="t",
        RM_PROD_URL=prod.url.replace("127.0.0.1", "localhost"),
        RM_PROD_TOKEN="t",
        REQUIRED="true",
    )
    assert result.returncode == 0, result.stderr
    assert len(staging.calls) == 1 and len(prod.calls) == 1


def _logging_curl(tmp_path: Path) -> tuple[str, Path]:
    """A PATH whose curl logs its arguments to the returned file, then runs the real curl."""
    args_log = tmp_path / "curl-args"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_curl = bin_dir / "curl"
    fake_curl.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$@" >>"{args_log}"\n'
        f'exec "{shutil.which("curl")}" "$@"\n'
    )
    fake_curl.chmod(0o755)
    return f"{bin_dir}{os.pathsep}{os.environ['PATH']}", args_log


def test_token_is_not_on_the_curl_command_line(rms, tmp_path: Path):
    staging, _ = rms
    path, args_log = _logging_curl(tmp_path)
    token = 'fake-token-with-"quote"-and-\\backslash'
    result = _run(
        RM_STAGING_URL=staging.url,
        RM_STAGING_TOKEN=token,
        REQUIRED="true",
        PATH=path,
    )
    assert result.returncode == 0, result.stderr
    args = args_log.read_text()
    assert "--config" in args
    assert "fake-token" not in args
    assert staging.calls[0]["auth"] == f"Bearer {token}"


def test_token_with_line_break_is_refused(rms):
    staging, _ = rms
    result = _run(RM_STAGING_URL=staging.url, RM_STAGING_TOKEN="a\nX-Injected: 1", REQUIRED="true")
    assert result.returncode == 1
    assert staging.calls == []


def test_meta_rm_request_lands_in_meta(rms):
    staging, _ = rms
    request_id = "0b6b2e1e-2d7c-4a7e-9d2e-6a0f8d2c1b3a"
    result = _run(RM_STAGING_URL=staging.url, RM_STAGING_TOKEN="t", META=f"rm_request={request_id}\n")
    assert result.returncode == 0, result.stderr
    assert staging.calls[0]["body"][0]["meta"]["rm_request"] == request_id


def test_release_declaration_file_is_sent(rms, tmp_path: Path):
    staging, prod = rms
    declaration = {
        "schemaVersion": "wire.component-release/v1alpha2",
        "component": "my-component",
        "version": "4.24.3",
        "summary": "Nothing to declare.",
        "upgrade_from": ">=4.23.0",
        "changes": [{"kind": "added", "description": "A feature", "breaking": False, "links": []}],
        "migrations": [],
        "configuration": [],
    }
    file = tmp_path / "release-declaration.json"
    file.write_text(json.dumps(declaration, indent=2))
    result = _run(
        RM_STAGING_URL=staging.url,
        RM_STAGING_TOKEN="t",
        RM_PROD_URL=prod.url,
        RM_PROD_TOKEN="t",
        REQUIRED="true",
        DECLARATION_FILE=str(file),
    )
    assert result.returncode == 0, result.stderr
    assert staging.calls[0]["body"][0]["release_declaration"] == declaration
    assert prod.calls[0]["body"][0]["release_declaration"] == declaration


def test_large_release_declaration_file_is_sent(rms, tmp_path: Path):
    # Above the 128 KB a single command line argument may hold on Linux.
    staging, prod = rms
    declaration = json.loads((ROOT / "testdata/release-declaration/valid.json").read_text())
    declaration["changes"] = [
        {"kind": "fixed", "description": f"Fix number {n}: " + "x" * 200, "breaking": False, "links": []} for n in range(1000)
    ]
    file = tmp_path / "release-declaration.json"
    file.write_text(json.dumps(declaration, indent=2))
    assert file.stat().st_size > 200 * 1024
    path, args_log = _logging_curl(tmp_path)
    result = _run(
        RM_STAGING_URL=staging.url,
        RM_STAGING_TOKEN="t",
        RM_PROD_URL=prod.url,
        RM_PROD_TOKEN="t",
        REQUIRED="true",
        DECLARATION_FILE=str(file),
        PATH=path,
    )
    assert result.returncode == 0, result.stderr
    assert "Fix number" not in args_log.read_text()
    assert staging.calls[0]["body"][0]["release_declaration"] == declaration
    assert prod.calls[0]["body"][0]["release_declaration"] == declaration


def test_no_declaration_file_sends_no_declaration(rms):
    staging, _ = rms
    result = _run(RM_STAGING_URL=staging.url, RM_STAGING_TOKEN="t", DECLARATION_FILE="")
    assert result.returncode == 0, result.stderr
    assert "release_declaration" not in staging.calls[0]["body"][0]


def test_missing_declaration_file_warns_and_skips(rms, tmp_path: Path):
    staging, prod = rms
    result = _run(
        RM_STAGING_URL=staging.url,
        RM_STAGING_TOKEN="t",
        RM_PROD_URL=prod.url,
        RM_PROD_TOKEN="t",
        DECLARATION_FILE=str(tmp_path / "missing.json"),
    )
    assert result.returncode == 0, result.stderr
    assert "::warning::release declaration file" in result.stdout
    assert "does not exist" in result.stdout
    assert staging.calls == [] and prod.calls == []


def test_missing_declaration_file_fails_when_required(rms, tmp_path: Path):
    staging, _ = rms
    result = _run(
        RM_STAGING_URL=staging.url,
        RM_STAGING_TOKEN="t",
        REQUIRED="true",
        DECLARATION_FILE=str(tmp_path / "missing.json"),
    )
    assert result.returncode == 1
    assert "::error::declaration failed: release declaration file" in result.stderr
    assert staging.calls == []


@pytest.mark.parametrize("content", ["{not json", '["an", "array"]', "", "{} {}"])
def test_invalid_declaration_file_is_a_failed_declaration(rms, tmp_path: Path, content: str):
    staging, _ = rms
    file = tmp_path / "release-declaration.json"
    file.write_text(content)
    result = _run(RM_STAGING_URL=staging.url, RM_STAGING_TOKEN="t", DECLARATION_FILE=str(file))
    assert result.returncode == 0, result.stderr
    assert "is not a JSON object" in result.stdout
    result = _run(RM_STAGING_URL=staging.url, RM_STAGING_TOKEN="t", REQUIRED="true", DECLARATION_FILE=str(file))
    assert result.returncode == 1
    assert "::error::declaration failed" in result.stderr
    assert staging.calls == []


MANIFEST = {
    "schemaVersion": "wire.component-release-manifest/v1alpha1",
    "component": "my-component",
    "version": "1.41.4",
    "kind": "ga",
    "compatibility": {
        "provides": [{"interface": "my-component/status-api", "supported": "1"}],
        "requires": [{"interface": "wire-server/admin-api", "range": "1", "class": "mandatory"}],
        "includes": [],
    },
}


def test_release_manifest_file_is_sent_with_the_declaration(rms, tmp_path: Path):
    staging, prod = rms
    manifest = tmp_path / "release-manifest.json"
    manifest.write_text(json.dumps(MANIFEST, indent=2))
    declaration = tmp_path / "release-declaration.json"
    declaration.write_text('{"schemaVersion": "wire.component-release/v1alpha2"}')
    result = _run(
        RM_STAGING_URL=staging.url,
        RM_STAGING_TOKEN="t",
        RM_PROD_URL=prod.url,
        RM_PROD_TOKEN="t",
        REQUIRED="true",
        MANIFEST_FILE=str(manifest),
        DECLARATION_FILE=str(declaration),
    )
    assert result.returncode == 0, result.stderr
    for rm in (staging, prod):
        record = rm.calls[0]["body"][0]
        assert record["manifest"] == MANIFEST
        assert record["release_declaration"] == {"schemaVersion": "wire.component-release/v1alpha2"}


def test_no_manifest_file_sends_no_manifest(rms):
    staging, _ = rms
    result = _run(RM_STAGING_URL=staging.url, RM_STAGING_TOKEN="t", MANIFEST_FILE="")
    assert result.returncode == 0, result.stderr
    assert "manifest" not in staging.calls[0]["body"][0]


@pytest.mark.parametrize("content", [None, "{not json", '["an", "array"]', "{} {}"])
def test_bad_manifest_file_is_a_failed_declaration(rms, tmp_path: Path, content):
    staging, _ = rms
    file = tmp_path / "release-manifest.json"
    if content is not None:
        file.write_text(content)
    result = _run(RM_STAGING_URL=staging.url, RM_STAGING_TOKEN="t", MANIFEST_FILE=str(file))
    assert result.returncode == 0, result.stderr
    assert "::warning::release manifest file" in result.stdout
    result = _run(RM_STAGING_URL=staging.url, RM_STAGING_TOKEN="t", REQUIRED="true", MANIFEST_FILE=str(file))
    assert result.returncode == 1
    assert "::error::declaration failed: release manifest file" in result.stderr
    assert staging.calls == []


# --- OIDC mode: a GitHub Actions OIDC token instead of an ingest token ---------

JWT = "eyJhbGciOiJSUzI1NiJ9.eyJhdWQiOiJ4In0.c2ln-_"
REQUEST_TOKEN = "runner-request-token"


class FakeIdp:
    """The runner's token endpoint: answers GET ?...&audience=<a> and records the calls."""

    def __init__(self, status: int = 200, body: bytes | None = None):
        self.status = status
        self.body = body
        self.calls: list[dict] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                query = parse_qs(urlparse(self.path).query)
                fake.calls.append(
                    {"auth": self.headers["Authorization"], "query": query, "path": self.path}
                )
                body = fake.body
                if body is None:
                    body = json.dumps({"value": JWT}).encode()
                self.send_response(fake.status)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/token?api-version=2.0"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.fixture
def idp():
    fake = FakeIdp()
    yield fake
    fake.close()


def _oidc_env(idp, **env: str) -> dict:
    return {
        "ACTIONS_ID_TOKEN_REQUEST_URL": idp.url,
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": REQUEST_TOKEN,
        **env,
    }


def test_oidc_token_requested_for_the_audience_and_sent_as_bearer(rms, idp):
    staging, _ = rms
    result = _run(
        RM_STAGING_URL=staging.url,
        RM_STAGING_AUDIENCE="wire-release-manager-staging",
        **_oidc_env(idp),
    )
    assert result.returncode == 0, result.stderr
    assert idp.calls[0]["query"]["audience"] == ["wire-release-manager-staging"]
    assert idp.calls[0]["query"]["api-version"] == ["2.0"]
    assert idp.calls[0]["auth"] == f"Bearer {REQUEST_TOKEN}"
    assert staging.calls[0]["auth"] == f"Bearer {JWT}"
    assert "::notice::my-component" in result.stdout


def test_oidc_token_is_masked_first_and_never_printed(rms, idp):
    staging, _ = rms
    staging.status = 500
    staging.body = b"nope"
    result = _run(
        RM_STAGING_URL=staging.url, RM_STAGING_AUDIENCE="aud", **_oidc_env(idp)
    )
    out = result.stdout + result.stderr
    assert out.count(JWT) == 1
    assert f"::add-mask::{JWT}" in out
    assert REQUEST_TOKEN not in out


def test_audience_is_url_encoded(rms, idp):
    staging, _ = rms
    result = _run(
        RM_STAGING_URL=staging.url, RM_STAGING_AUDIENCE="a b&c=d/e", **_oidc_env(idp)
    )
    assert result.returncode == 0, result.stderr
    assert idp.calls[0]["query"]["audience"] == ["a b&c=d/e"]
    assert "&c=d" not in idp.calls[0]["path"].split("audience=", 1)[1]


def test_a_set_token_wins_over_the_audience(rms, idp):
    staging, _ = rms
    result = _run(
        RM_STAGING_URL=staging.url,
        RM_STAGING_TOKEN="ingest-token",
        RM_STAGING_AUDIENCE="aud",
        **_oidc_env(idp),
    )
    assert result.returncode == 0, result.stderr
    assert idp.calls == []
    assert staging.calls[0]["auth"] == "Bearer ingest-token"


def test_each_release_manager_gets_a_token_for_its_audience(rms, idp):
    staging, prod = rms
    result = _run(
        RM_STAGING_URL=staging.url,
        RM_STAGING_AUDIENCE="staging-aud",
        RM_PROD_URL=prod.url,
        RM_PROD_TOKEN="p-token",
        **_oidc_env(idp),
    )
    assert result.returncode == 0, result.stderr
    assert [c["query"]["audience"] for c in idp.calls] == [["staging-aud"]]
    assert prod.calls[0]["auth"] == "Bearer p-token"


def test_missing_id_token_permission_warns_and_posts_nothing(rms):
    staging, _ = rms
    result = _run(RM_STAGING_URL=staging.url, RM_STAGING_AUDIENCE="aud")
    assert result.returncode == 0, result.stderr
    assert staging.calls == []
    assert "id-token: write" in result.stdout
    assert "::warning::release manager staging" in result.stdout


def test_missing_id_token_permission_fails_when_required(rms):
    staging, _ = rms
    result = _run(RM_STAGING_URL=staging.url, RM_STAGING_AUDIENCE="aud", REQUIRED="true")
    assert result.returncode == 1
    assert staging.calls == []


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (500, b'{"value": "' + JWT.encode() + b'"}'),
        (200, b"not json"),
        (200, b'{"value": ""}'),
        (200, b'{"value": "a.b.c\\n::error::injected"}'),
        (200, b'{"value": "has space.b.c"}'),
        (200, b'{"other": 1}'),
    ],
    ids=["http-500", "not-json", "empty", "injection", "bad-shape", "no-value"],
)
def test_a_bad_token_answer_warns_and_posts_nothing(rms, status, body):
    staging, _ = rms
    bad = FakeIdp(status=status, body=body)
    try:
        result = _run(
            RM_STAGING_URL=staging.url, RM_STAGING_AUDIENCE="aud", **_oidc_env(bad)
        )
    finally:
        bad.close()
    assert result.returncode == 0, result.stderr
    assert staging.calls == []
    assert "no OIDC token" in result.stdout
    assert "injected" not in result.stdout + result.stderr
    # Only the release manager URL and its host are masked, never a token.
    masks = {line for line in result.stdout.splitlines() if line.startswith("::add-mask::")}
    assert masks <= {f"::add-mask::{staging.url.rstrip('/')}", "::add-mask::127.0.0.1"}


def test_the_oidc_endpoint_must_be_https(rms):
    staging, _ = rms
    result = _run(
        RM_STAGING_URL=staging.url,
        RM_STAGING_AUDIENCE="aud",
        ACTIONS_ID_TOKEN_REQUEST_URL="http://evil.example/token?x=1",
        ACTIONS_ID_TOKEN_REQUEST_TOKEN=REQUEST_TOKEN,
    )
    assert result.returncode == 0, result.stderr
    assert staging.calls == []
    assert "not usable" in result.stdout


def test_the_oidc_token_never_goes_to_a_non_https_release_manager(idp):
    result = _run(
        RM_STAGING_URL="http://rm.example",
        RM_STAGING_AUDIENCE="aud",
        **_oidc_env(idp),
    )
    assert result.returncode == 0, result.stderr
    assert idp.calls == []
    assert "not an https:// URL" in result.stdout


def test_without_token_or_audience_nothing_changes(rms, idp):
    staging, _ = rms
    result = _run(RM_STAGING_URL=staging.url, **_oidc_env(idp))
    assert result.returncode == 0, result.stderr
    assert idp.calls == [] and staging.calls == []
    assert "no ingest token" in result.stdout


def test_a_blank_audience_is_not_an_audience(rms, idp):
    staging, _ = rms
    result = _run(RM_STAGING_URL=staging.url, RM_STAGING_AUDIENCE="   ", **_oidc_env(idp))
    assert result.returncode == 0, result.stderr
    assert idp.calls == [] and staging.calls == []
    assert "no ingest token" in result.stdout
