"""The workflow templates call actions of this repository that exist, at @dev or at one
release, and share the publication concurrency group."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = sorted((ROOT / "templates").glob("*.yml"))
USES = re.compile(r"uses: wireapp/wire-rm-actions/([^@\s]+)@(\S+)")


def test_there_are_templates():
    assert TEMPLATES


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_actions_exist_at_one_ref(template: Path):
    uses = USES.findall(template.read_text())
    assert uses
    for action, _ in uses:
        assert (ROOT / action / "action.yml").is_file(), f"{template.name}: no action {action}"
    assert len({ref for _, ref in uses}) == 1, f"{template.name}: several refs"


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_publication_lock(template: Path):
    text = template.read_text()
    assert "group: publish-${{ github.repository }}" in text
    assert "cancel-in-progress: false" in text
