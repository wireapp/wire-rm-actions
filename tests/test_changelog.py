"""The release changelog written by scripts/changelog.sh.

The expected text is what generate-changelog 1.8.0 (the release changelog script of the components) writes for the same commits.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/changelog.sh"
URL = "https://github.com/wireapp/example"
DATE = "2026-10-09"

SUBJECTS = [
    "feat(api): add search",
    "chore: bump deps",
    "fix: crash on empty team (#42)",
    "feat(api): paginate search (#43)",
    "Merge pull request #44 from wireapp/x",
    "feat: drop legacy endpoint [breaking]",
    "Feat(ui): Upper-case type",
    "runfix: quick fix",
    "perf!: faster boot",
    "fix: ",
    "docs: readme",
    "fix(api): handle 404, again: retry",
]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "src"
    path.mkdir()
    _git(path, "init", "-q", "-b", "dev")
    for k, v in (("user.email", "test@example.com"), ("user.name", "Test"), ("commit.gpgsign", "false")):
        _git(path, "config", k, v)
    _git(path, "commit", "-q", "--allow-empty", "-m", "feat: before the tag")
    _git(path, "tag", "v1.0.0")
    for i, subject in enumerate(SUBJECTS):
        date = f"2026-10-01T10:00:{i:02d}+00:00"
        env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
        subprocess.run(
            ["git", "-C", str(path), "commit", "-q", "--allow-empty", "-m", subject],
            check=True, env=env,
        )
    return path


def _run(repo: Path, **env: str) -> subprocess.CompletedProcess:
    clean = {k: v for k, v in os.environ.items() if k != "GITHUB_OUTPUT"}
    return subprocess.run(
        ["bash", str(SCRIPT)], cwd=repo, env={**clean, "DATE": DATE, **env},
        capture_output=True, text=True,
    )


def _changelog(repo: Path, **env: str) -> tuple[str, dict[str, str]]:
    result = _run(repo, **{"FROM_REF": "v1.0.0", **env})
    assert result.returncode == 0, result.stderr
    outputs = dict(line.split("=", 1) for line in result.stdout.splitlines())
    return (repo / outputs["file"]).read_text(), outputs


def _link(repo: Path, subject: str) -> str:
    sha = _git(repo, "log", "--format=%H", "--fixed-strings", f"--grep={subject}", "-1")
    assert sha, subject
    return f"([{sha[:8]}]({URL}/commit/{sha}))"


def test_release_format(repo: Path) -> None:
    text, outputs = _changelog(repo, VERSION="1.1.0", REPO_URL=URL)
    link = lambda s: _link(repo, s)  # noqa: E731
    assert outputs == {"file": "CHANGELOG.md", "count": "7"}
    assert text == "\n".join([
        f"#### 1.1.0 ({DATE})",
        "",
        "##### Breaking Changes",
        "",
        f"*  drop legacy endpoint [breaking] {link('drop legacy endpoint')}",
        "",
        "##### New Features",
        "",
        f"* **ui:**  Upper-case type {link('Upper-case type')}",
        "* **api:**",
        f"  *  paginate search ([#43]({URL}/pull/43)) {link('paginate search')}",
        f"  *  add search {link('add search')}",
        "",
        "##### Bug Fixes",
        "",
        f"* **api:**  handle 404, again: retry {link('handle 404')}",
        f"*  crash on empty team ([#42]({URL}/pull/42)) {link('crash on empty team')}",
        "",
        "##### Other Changes",
        "",
        f"*  faster boot {link('faster boot')}",
        "",
        "",
    ])


def test_without_heading_nor_links(repo: Path) -> None:
    text, _ = _changelog(repo, HEADING="false", EXCLUDE="feat fix chore docs runfix breaking")
    sha = _git(repo, "log", "--format=%H", "--grep=faster boot", "-1")
    assert text == f"##### Other Changes\n\n*  faster boot ({sha[:8]})\n\n"


def test_no_exclusion_and_version_less_heading(repo: Path) -> None:
    text, outputs = _changelog(repo, EXCLUDE="")
    assert text.startswith(f"#### {DATE}\n\n##### Breaking Changes\n")
    assert "##### Chores" in text and "##### Documentation Changes" in text
    # runfix is no conventional type: it lands in Other Changes.
    assert "*  quick fix (" in text.split("##### Other Changes")[1]
    assert outputs["count"] == "10"


def test_empty_range(repo: Path) -> None:
    _git(repo, "tag", "v1.1.0")
    text, outputs = _changelog(repo, FROM_REF="v1.1.0", VERSION="1.1.1")
    assert text == f"#### 1.1.1 ({DATE})\n\n"
    assert outputs["count"] == "0"


def test_to_ref_and_output_file(repo: Path, tmp_path: Path) -> None:
    out = tmp_path / "notes.md"
    text, outputs = _changelog(repo, TO_REF="HEAD~11", OUTPUT_FILE=str(out), HEADING="false")
    assert outputs["file"] == str(out)
    assert text.startswith("##### New Features\n\n* **api:**  add search (")


def test_github_output(repo: Path, tmp_path: Path) -> None:
    gh = tmp_path / "gh_output"
    result = _run(repo, FROM_REF="v1.0.0", GITHUB_OUTPUT=str(gh))
    assert result.returncode == 0, result.stderr
    assert gh.read_text() == "file=CHANGELOG.md\ncount=7\n"


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({}, "FROM_REF is required"),
        ({"FROM_REF": "v9.9.9"}, "unknown ref: v9.9.9"),
        ({"FROM_REF": "--all"}, "unknown ref: --all"),
        ({"FROM_REF": "v1.0.0", "TO_REF": "nope"}, "unknown ref: nope"),
        ({"FROM_REF": "v1.0.0", "REPO_URL": "javascript:alert(1)"}, "REPO_URL must be"),
        ({"FROM_REF": "v1.0.0", "VERSION": "1.0.0 $(id)"}, "invalid VERSION"),
        ({"FROM_REF": "v1.0.0", "HEADING": "no"}, "HEADING must be true or false"),
        ({"FROM_REF": "v1.0.0", "DATE": "today"}, "DATE must be YYYY-MM-DD"),
    ],
)
def test_rejects(repo: Path, env: dict[str, str], message: str) -> None:
    result = _run(repo, **env)
    assert result.returncode != 0
    assert message in result.stderr


def test_shallow_clone(repo: Path, tmp_path: Path) -> None:
    clone = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{repo}", str(clone)], check=True
    )
    result = _run(clone, FROM_REF="v1.0.0")
    assert result.returncode != 0
    assert "fetch-depth: 0" in result.stderr


def test_subject_links_and_html_are_neutralized(repo: Path) -> None:
    subject = "fix(<b>): see [here](https://evil) ![x](https://e/i.png) <img src=x> #12"
    _git(repo, "commit", "-q", "--allow-empty", "-m", subject)
    text, _ = _changelog(repo, REPO_URL=URL)
    sha = _git(repo, "rev-parse", "HEAD")
    assert (
        "* **&lt;b&gt;:**  see [here]&#x28;https://evil) ![x]&#x28;https://e/i.png) "
        f"&lt;img src=x&gt; [#12]({URL}/pull/12) ([{sha[:8]}]({URL}/commit/{sha}))"
    ) in text.splitlines()


# Merge commits, as GitHub makes them: "Merge pull request #N from ..." keeps the number of the
# pull request, which its commits do not carry.
PULL_REQUESTS = [
    (7, ["feat(api): add a", "fix: b"]),
    (8, ["ci: c"]),
    (10, ["feat: e, see #5"]),
    (11, ["fix: already linked (#11)"]),
]


@pytest.fixture
def merged(tmp_path: Path) -> Path:
    path = tmp_path / "merged"
    path.mkdir()
    _git(path, "init", "-q", "-b", "dev")
    for k, v in (("user.email", "test@example.com"), ("user.name", "Test"), ("commit.gpgsign", "false")):
        _git(path, "config", k, v)
    tick = iter(range(60))

    def commit(*args: str) -> None:
        date = f"2026-10-01T10:00:{next(tick):02d}+00:00"
        env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
        subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, env=env)

    commit("commit", "-q", "--allow-empty", "-m", "feat: before the tag")
    _git(path, "tag", "v1.0.0")
    for number, subjects in PULL_REQUESTS:
        _git(path, "checkout", "-q", "-b", f"pr{number}", "dev")
        for subject in subjects:
            commit("commit", "-q", "--allow-empty", "-m", subject)
        _git(path, "checkout", "-q", "dev")
        commit("merge", "-q", "--no-ff", f"pr{number}", "-m", f"Merge pull request #{number} from wireapp/pr{number}")
    commit("commit", "-q", "--allow-empty", "-m", "fix: squashed (#9)")
    commit("commit", "-q", "--allow-empty", "-m", "fix: straight on dev")
    _git(path, "checkout", "-q", "-b", "side", "dev")
    commit("commit", "-q", "--allow-empty", "-m", "fix: side work")
    _git(path, "checkout", "-q", "dev")
    commit("merge", "-q", "--no-ff", "side", "-m", "Merge branch 'side' into dev")
    return path


def _pr(number: int) -> str:
    return f"([#{number}]({URL}/pull/{number}))"


def test_merge_commits_are_ignored_by_default(merged: Path) -> None:
    text, outputs = _changelog(merged, REPO_URL=URL, HEADING="false", EXCLUDE="")
    assert outputs["count"] == "8"
    assert f"([#7]" not in text and "#5]" in text
    assert f"*  squashed {_pr(9)} {_link(merged, 'squashed')}" in text.splitlines()
    assert f"*  straight on dev {_link(merged, 'straight on dev')}" in text.splitlines()


def test_pull_request_links_of_merge_commits(merged: Path) -> None:
    text, outputs = _changelog(
        merged, REPO_URL=URL, HEADING="false", EXCLUDE="", MERGE_COMMITS="pull-request"
    )
    lines = text.splitlines()
    link = lambda s: _link(merged, s)  # noqa: E731
    assert outputs["count"] == "8"
    # the merge brings its number to every commit of the branch
    assert "* **api:**  add a " + f"{_pr(7)} {link('add a')}" in lines
    assert f"*  b {_pr(7)} {link('fix: b')}" in lines
    assert f"*  c {_pr(8)} {link('ci: c')}" in lines
    # a number in the subject is another reference: the pull request link follows it
    assert f"*  e, see [#5]({URL}/pull/5) {_pr(10)} {link('e, see')}" in lines
    # the subject already links the pull request: no second link
    assert f"*  already linked {_pr(11)} {link('already linked')}" in lines
    # a squashed commit and a commit straight on dev are as without the option
    assert f"*  squashed {_pr(9)} {link('squashed')}" in lines
    assert f"*  straight on dev {link('straight on dev')}" in lines
    # a merge that is no pull request merge gives no number
    assert f"*  side work {link('side work')}" in lines


def test_pull_request_without_repo_url(merged: Path) -> None:
    text, _ = _changelog(merged, HEADING="false", EXCLUDE="", MERGE_COMMITS="pull-request")
    assert any(line.startswith("*  c (#8) (") for line in text.splitlines())


def test_commit_keeps_the_first_pull_request_that_carried_it(merged: Path) -> None:
    # dev is merged into a second branch that merges back: the commits are in two merges
    _git(merged, "checkout", "-q", "-b", "again", "dev")
    _git(merged, "commit", "-q", "--allow-empty", "-m", "fix: again")
    _git(merged, "checkout", "-q", "dev")
    _git(merged, "merge", "-q", "--no-ff", "again", "-m", "Merge pull request #20 from wireapp/again")
    _git(merged, "merge", "-q", "--no-ff", "--allow-unrelated-histories", "again", "-m", "Merge pull request #21 from wireapp/again")
    text, _ = _changelog(merged, REPO_URL=URL, HEADING="false", MERGE_COMMITS="pull-request")
    assert f"*  again {_pr(20)} " in text


def test_collapse_folds_sections_after_the_others(merged: Path) -> None:
    text, outputs = _changelog(
        merged, REPO_URL=URL, VERSION="1.1.0", EXCLUDE="", COLLAPSE="ci, chore",
        MERGE_COMMITS="pull-request",
    )
    lines = text.splitlines()
    assert outputs["count"] == "8"
    assert lines.index("##### New Features") < lines.index("<summary>Continuous Integration (1)</summary>")
    assert lines.index("##### Bug Fixes") < lines.index("<details>")
    block = lines[lines.index("<details>"):]
    assert block[:4] == ["<details>", "<summary>Continuous Integration (1)</summary>", "", f"*  c {_pr(8)} {_link(merged, 'ci: c')}"]
    assert block[4:] == ["", "</details>", ""]
    assert "##### Continuous Integration" not in text


def test_collapse_of_an_excluded_type_leaves_it_out(merged: Path) -> None:
    text, _ = _changelog(merged, HEADING="false", EXCLUDE="ci", COLLAPSE="ci")
    assert "<details>" not in text and "Continuous Integration" not in text


def test_collapse_keeps_the_heading_of_the_other_sections(merged: Path) -> None:
    text, _ = _changelog(merged, HEADING="false", EXCLUDE="", COLLAPSE="feat fix")
    lines = text.splitlines()
    assert lines[0] == "##### Continuous Integration"
    assert "##### New Features" not in text and "##### Bug Fixes" not in text
    assert lines.count("<details>") == 2
    assert lines.index("<summary>New Features (2)</summary>") < lines.index("<summary>Bug Fixes (5)</summary>")


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"MERGE_COMMITS": "all"}, "MERGE_COMMITS must be ignore or pull-request"),
        ({"COLLAPSE": "ci; rm"}, "COLLAPSE must list commit types"),
        ({"COLLAPSE": "CI"}, "COLLAPSE must list commit types"),
        ({"COLLAPSE": "ci,breaking"}, "COLLAPSE cannot fold the breaking changes"),
    ],
)
def test_rejects_new_inputs(repo: Path, env: dict[str, str], message: str) -> None:
    result = _run(repo, FROM_REF="v1.0.0", **env)
    assert result.returncode != 0
    assert message in result.stderr
