"""scripts/release-documents.sh: the release note and the release declaration of
a release or a dev build, and the documents object of its manifest."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/release-documents.sh"
VALID = json.loads((ROOT / "testdata/release-declaration/valid-v1alpha2.json").read_text())
ENV_KEYS = (
    "RELEASE_TYPE", "VERSION", "COMPONENT", "RELEASE_NOTE", "NOTE_INPUT", "RELEASE_DECLARATION",
    "OUT_DIR", "GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY",
    "PUBLICATION_DIR",
)


def _declaration(version: str, changes: dict | None = None) -> dict:
    return {**VALID, "component": "my-component", "version": version, **(changes or {})}


def _run(cwd: Path, **env: str) -> subprocess.CompletedProcess:
    clean = {k: v for k, v in os.environ.items() if k not in ENV_KEYS}
    return subprocess.run(
        ["bash", str(SCRIPT)], cwd=cwd, env={**clean, "COMPONENT": "my-component", **env}, capture_output=True, text=True
    )


def _outputs(result: subprocess.CompletedProcess) -> dict[str, str]:
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line and " " not in line.split("=", 1)[0])


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "publication").mkdir()
    return tmp_path


def _note(repo: Path, text: str = "# note\n") -> Path:
    path = repo / "publication/release-note.md"
    path.write_text(text)
    return path


def test_ga_note_and_repository_declaration(repo: Path):
    _note(repo)
    (repo / "publication/declaration.json").write_text(json.dumps(_declaration("1.41.4"), indent=2))
    result = _run(repo, RELEASE_TYPE="ga", VERSION="1.41.4", OUT_DIR="out")
    assert result.returncode == 0, result.stderr
    out = _outputs(result)
    assert out["note-source"] == "repository" and out["declaration-source"] == "repository"
    written = (repo / "out/release-declaration.json").read_text()
    assert written == json.dumps(_declaration("1.41.4"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    documents = json.loads(out["documents-json"])
    assert documents["release_note"] == {
        "file": "release-note.md",
        "sha256": hashlib.sha256(b"# note\n").hexdigest(),
        "source": "repository",
    }
    assert documents["release_declaration"]["sha256"] == hashlib.sha256(written.encode()).hexdigest()


def test_the_input_declaration_is_kept_byte_for_byte(repo: Path):
    _note(repo)
    text = json.dumps(_declaration("1.41.4")) + "  "
    result = _run(repo, RELEASE_TYPE="ga", VERSION="1.41.4", RELEASE_DECLARATION=text, OUT_DIR="out")
    assert result.returncode == 0, result.stderr
    assert _outputs(result)["declaration-source"] == "release_manager"
    assert (repo / "out/release-declaration.json").read_text() == text


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"RELEASE_TYPE": "ga", "VERSION": "1.41.4"}, "no release note for GA 1.41.4"),
        ({"RELEASE_TYPE": "nightly", "VERSION": "1.41.4"}, "RELEASE_TYPE must be one of"),
        ({"RELEASE_TYPE": "ga", "VERSION": "v1.41.4"}, "is not X.Y.Z"),
        ({"RELEASE_TYPE": "dev", "VERSION": "1.41.4"}, "is not a dev version"),
        ({"RELEASE_TYPE": "ga", "VERSION": "1.41.4", "COMPONENT": ""}, "COMPONENT is required"),
        ({"RELEASE_TYPE": "ga", "VERSION": "1.41.4", "NOTE_INPUT": "maybe"}, "NOTE_INPUT must be ignore or override"),
    ],
)
def test_refused(repo: Path, env: dict, message: str):
    result = _run(repo, **env)
    assert result.returncode == 1
    assert message in result.stderr


def test_ga_without_declaration_fails(repo: Path):
    _note(repo)
    result = _run(repo, RELEASE_TYPE="ga", VERSION="1.41.4", OUT_DIR="out")
    assert result.returncode == 1
    assert "no release declaration for GA 1.41.4" in result.stderr


def test_a_prerelease_goes_without_note_nor_declaration(repo: Path):
    result = _run(repo, RELEASE_TYPE="alpha", VERSION="1.41.4-alpha.1", OUT_DIR="out")
    assert result.returncode == 0, result.stderr
    assert "::warning::no release note for 1.41.4-alpha.1" in result.stderr
    assert _outputs(result)["documents-json"] == "{}"


@pytest.mark.parametrize(
    ("changes", "message"),
    [({"component": "wire-server"}, "component"), ({"version": "1.41.3"}, "version"), ({"summary": ""}, "summary")],
)
def test_an_invalid_declaration_fails(repo: Path, changes: dict, message: str):
    _note(repo)
    result = _run(
        repo, RELEASE_TYPE="ga", VERSION="1.41.4", OUT_DIR="out",
        RELEASE_DECLARATION=json.dumps(_declaration("1.41.4", changes)),
    )
    assert result.returncode == 1
    assert "is invalid for my-component 1.41.4" in result.stderr
    assert message in result.stderr


def test_the_note_input_is_ignored_by_default(repo: Path):
    _note(repo, "# from the repository\n")
    result = _run(repo, RELEASE_TYPE="rc", VERSION="1.41.4-rc.1", RELEASE_NOTE="# from the input", OUT_DIR="out")
    assert result.returncode == 0, result.stderr
    assert "the release_note input (16 characters) is ignored" in result.stderr
    assert (repo / "out/release-note.md").read_text() == "# from the repository\n"


def test_the_note_input_overrides_when_asked(repo: Path):
    _note(repo, "# from the repository\n")
    result = _run(
        repo, RELEASE_TYPE="rc", VERSION="1.41.4-rc.1", RELEASE_NOTE="# from the input",
        NOTE_INPUT="override", OUT_DIR="out",
    )
    assert result.returncode == 0, result.stderr
    assert _outputs(result)["note-source"] == "input"
    assert (repo / "out/release-note.md").read_text() == "# from the input\n"


def test_dev_references_the_note_of_the_version_it_leads_to(repo: Path):
    _note(repo)
    result = _run(repo, RELEASE_TYPE="dev", VERSION="1.41.4-alpha.8.20261011083037.gde43876", OUT_DIR="out")
    assert result.returncode == 0, result.stderr
    documents = json.loads(_outputs(result)["documents-json"])
    assert documents == {
        "release_note": {
            "file": "publication/release-note.md",
            "sha256": hashlib.sha256(b"# note\n").hexdigest(),
            "source": "repository",
        }
    }
    assert not (repo / "out/release-note.md").exists()


def test_dev_without_note_warns(repo: Path):
    _note(repo, "\n  \n")
    summary = repo / "summary.md"
    result = _run(repo, RELEASE_TYPE="dev", VERSION="1.41.5-20261014120000.g348ddc0", GITHUB_STEP_SUMMARY=str(summary))
    assert result.returncode == 0, result.stderr
    assert "::warning title=No release note for 1.41.5::publication/release-note.md is missing or empty" in result.stdout
    assert _outputs(result)["documents-json"] == "{}"
    assert "no release note for 1.41.5" in summary.read_text()


def test_dev_carries_no_declaration(repo: Path):
    (repo / "publication/declaration.json").write_text("{}")
    result = _run(
        repo, RELEASE_TYPE="dev", VERSION="1.41.5-20261014120000.g348ddc0", RELEASE_DECLARATION="{}",
    )
    assert result.returncode == 0, result.stderr
    assert "RELEASE_DECLARATION is ignored for a dev build" in result.stderr
    assert "release_declaration" not in _outputs(result)["documents-json"]


def test_outputs_go_to_github_output(repo: Path):
    output = repo / "github-output"
    result = _run(repo, RELEASE_TYPE="alpha", VERSION="1.41.4-alpha.1", OUT_DIR="out", GITHUB_OUTPUT=str(output))
    assert result.returncode == 0, result.stderr
    assert "documents-json={}" in output.read_text().splitlines()


# --- publication/ with the full fixture ---------------------------------------------


def _publication(repo: Path, version: str = "1.41.5", note: str = "# 1.41.5\n") -> None:
    (repo / "publication").mkdir(exist_ok=True)
    (repo / "publication/release-note.md").write_text(note)
    doc = {**VALID, "component": "my-component", "version": version}
    (repo / "publication/declaration.json").write_text(json.dumps(doc, indent=2))


def test_ga_reads_publication(repo: Path):
    _publication(repo)
    result = _run(repo, RELEASE_TYPE="ga", VERSION="1.41.5", OUT_DIR="out")
    assert result.returncode == 0, result.stderr
    out = _outputs(result)
    assert (out["note-path"], out["note-source"], out["declaration-source"]) == (
        "publication/release-note.md", "repository", "repository",
    )
    assert (repo / "out/release-note.md").read_text() == "# 1.41.5\n"
    assert json.loads((repo / "out/release-declaration.json").read_text())["schemaVersion"] == "wire.component-release/v1alpha2"


def test_a_prerelease_checks_the_v1alpha2_declaration_against_its_ga(repo: Path):
    _publication(repo)
    result = _run(repo, RELEASE_TYPE="rc", VERSION="1.41.5-rc.1", OUT_DIR="out")
    assert result.returncode == 0, result.stderr
    assert "valid release declaration of my-component 1.41.5" in result.stdout


def test_a_v1alpha2_declaration_of_another_version_fails(repo: Path):
    _publication(repo, version="1.41.4")
    result = _run(repo, RELEASE_TYPE="ga", VERSION="1.41.5", OUT_DIR="out")
    assert result.returncode == 1
    assert "version is '1.41.4', expected '1.41.5'" in result.stderr


def test_ga_without_any_note_names_publication(repo: Path):
    result = _run(repo, RELEASE_TYPE="ga", VERSION="1.41.5", OUT_DIR="out")
    assert result.returncode == 1
    assert "no release note for GA 1.41.5: expected publication/release-note.md" in result.stderr


def test_dev_references_the_publication_note(repo: Path):
    _publication(repo)
    result = _run(repo, RELEASE_TYPE="dev", VERSION="1.41.5-20261016154957.gc2144ee")
    assert result.returncode == 0, result.stderr
    assert json.loads(_outputs(result)["documents-json"])["release_note"]["file"] == "publication/release-note.md"


def test_another_publication_dir(repo: Path):
    (repo / "release").mkdir()
    (repo / "release/release-note.md").write_text("# other\n")
    result = _run(repo, RELEASE_TYPE="rc", VERSION="1.41.5-rc.1", OUT_DIR="out", PUBLICATION_DIR="release")
    assert result.returncode == 0, result.stderr
    assert _outputs(result)["note-path"] == "release/release-note.md"
