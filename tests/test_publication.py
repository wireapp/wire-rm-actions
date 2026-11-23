"""The publication files of this repository (docs/releasing.md) pass the checks the actions
apply to a component, and the release workflows call actions that exist."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLICATION = ROOT / "publication"
WORKFLOWS = [ROOT / ".github/workflows/prepare-release.yml", ROOT / ".github/workflows/publish-release.yml"]
COMPONENT = "wire-rm-actions"


def _clean_env(*names: str) -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in names}


def _declaration() -> dict:
    return json.loads((PUBLICATION / "declaration.json").read_text())


def test_the_three_files_are_there():
    for name in ("compatibility.yaml", "release-note.md", "declaration.json"):
        assert (PUBLICATION / name).stat().st_size > 0, name


def test_declaration_is_valid_for_this_component():
    declaration = _declaration()
    assert declaration["component"] == COMPONENT
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/release-declaration.sh"), str(PUBLICATION / "declaration.json")],
        env={**_clean_env("FILE", "COMPONENT", "VERSION", "SCHEMA"), "COMPONENT": COMPONENT, "VERSION": declaration["version"]},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_declaration_is_formatted():
    text = (PUBLICATION / "declaration.json").read_text()
    formatted = subprocess.run(
        ["jq", "--indent", "2", "."], input=text, capture_output=True, text=True, check=True
    ).stdout
    assert text == formatted, "publication/declaration.json: run jq --indent 2 on it"


def test_release_note_names_the_declared_version():
    first_line = (PUBLICATION / "release-note.md").read_text().splitlines()[0]
    assert first_line.startswith("# ")
    assert _declaration()["version"] in first_line


def test_compatibility_file_passes(tmp_path: Path):
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/compatibility.sh")], cwd=ROOT,
        env={**_clean_env("FILE", "OUTPUT_DIR", "GITHUB_OUTPUT"), "OUTPUT_DIR": str(tmp_path)},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    document = json.loads((tmp_path / "compatibility.json").read_text())
    assert set(document) == {"providesApis", "consumesApis", "dependsOn", "includes"}


def test_release_documents_of_a_ga_are_complete(tmp_path: Path):
    version = _declaration()["version"]
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/release-documents.sh")], cwd=ROOT,
        env={
            **_clean_env("GITHUB_OUTPUT", "RELEASE_NOTE", "RELEASE_DECLARATION"),
            "COMPONENT": COMPONENT, "VERSION": version, "RELEASE_TYPE": "ga", "OUT_DIR": str(tmp_path),
        },
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "release-note.md").read_text() == (PUBLICATION / "release-note.md").read_text()
    assert json.loads((tmp_path / "release-declaration.json").read_text()) == _declaration()


def test_release_workflows_call_actions_of_this_repository():
    for workflow in WORKFLOWS:
        text = workflow.read_text()
        local = re.findall(r"uses: \./([a-z-]+)$", text, re.M)
        assert local, workflow.name
        for action in local:
            assert (ROOT / action / "action.yml").is_file(), f"{workflow.name}: no action {action}"
        remote = re.findall(r"^\s+uses: wireapp/wire-rm-actions/.*$", text, re.M)
        assert not remote, f"{workflow.name}: a release of the actions cannot pin itself: {remote}"
