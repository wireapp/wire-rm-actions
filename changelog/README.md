[wire-rm-actions](../README.md) ·
[version](../version/README.md) ·
[build-image](../build-image/README.md) ·
[quay-login](../quay-login/README.md) ·
[publish-chart](../publish-chart/README.md) ·
[notify-rm](../notify-rm/README.md) ·
**changelog** ·
[release-declaration](../release-declaration/README.md) ·
[release-documents](../release-documents/README.md) ·
[release-manifest](../release-manifest/README.md) ·
[compatibility](../compatibility/README.md) ·
[release-inputs](../release-inputs/README.md) ·
[release-source](../release-source/README.md) ·
[promote-image](../promote-image/README.md) ·
[ci-gate](../ci-gate/README.md) ·
[draft-release](../draft-release/README.md) ·
[publish-chart-s3](../publish-chart-s3/README.md)

# changelog

> The changelog of the commits since a release tag, in the generate-changelog
> release format, from conventional commit messages.

## Definition

`changelog` reads the commits of `from-tag..to-ref` and writes a markdown
changelog: one section per conventional commit type, commits grouped by scope,
with commit and pull request links. The output fits a `CHANGELOG.md` or, with
`heading: false`, a GitHub Release body.

```markdown
#### 5.3.0 (2026-10-12)

##### New Features

* **api:**
  *  paginate search ([#43](https://github.com/wireapp/example/pull/43)) ([1a2b3c4d](https://github.com/wireapp/example/commit/1a2b3c4d…))
  *  add search ([5e6f7a8b](https://github.com/wireapp/example/commit/5e6f7a8b…))

##### Bug Fixes

*  crash on empty team ([#42](https://github.com/wireapp/example/pull/42)) ([9c0d1e2f](https://github.com/wireapp/example/commit/9c0d1e2f…))
```

## Technical reference

### Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `from-tag` | yes | | The previous release tag; its commits are left out. |
| `to-ref` | no | `HEAD` | Last commit included. |
| `version` | no | `""` | Version in the `#### <version> (<date>)` heading; empty shows the date only. |
| `heading` | no | `"true"` | `"false"` leaves the heading out (GitHub Release body). |
| `exclude` | no | `chore build docs refactor style test runfix` | Commit types left out, comma or space separated. |
| `merge-commits` | no | `ignore` | `pull-request`: the commits of a `Merge pull request #N` merge get that pull request's link. The merge itself is left out either way. |
| `collapse` | no | `""` | Commit types whose section is folded in a `<details>` block after the other sections, comma or space separated (e.g. `ci`). |
| `repo-url` | no | the current repository URL | Base of the commit and pull request links; empty means no links. |
| `output-file` | no | `CHANGELOG.md` | Where the changelog is written. |

### Outputs

| Output | Example | Description |
|---|---|---|
| `file` | `CHANGELOG.md` | Path of the changelog. |
| `count` | `7` | Number of commits listed; `0` means no user-facing change. |

### Requirements

- `actions/checkout` with `fetch-depth: 0`, so that `from-tag` is reachable.
- `bash`, `git` and `awk`: nothing to install.

### Behaviour

- A subject is `type(scope): text` or `type: text`, as in generate-changelog:
  anything else (merge commits included) is left out.
- Sections, in this order: Breaking Changes, Build System / Dependencies,
  Chores, Continuous Integration, Documentation Changes, New Features, Bug
  Fixes, Other Changes, Performance Improvements, Refactors, Reverts, Code
  Style Changes, Tests. An unknown type goes to Other Changes.
- A subject ending in `[breaking]` (or a flag list holding `breaking`) goes to
  Breaking Changes, whatever its type.
- Commits are listed newest first. `#123` becomes a pull request link and each
  entry ends with its commit link, when `repo-url` is set.
- With `merge-commits: pull-request`, a repository that merges with merge
  commits (`Merge pull request #12 from ...`) gets the pull request link on
  every commit the merge brought in, as the squash and rebase merges already
  have it in the subject (`(#12)`): `([#12](<repo>/pull/12))`, before the commit
  link. A commit that already links that number gets no second link, and keeps
  the first pull request that carried it when two merges did. Merges that are
  not pull request merges (`Merge branch ...`) give no number.
- With `collapse: ci` (any list of types), those sections are written after the
  others, each as `<details><summary>Continuous Integration (3)</summary>` with
  its list inside, so what readers act on stays on top. Breaking Changes is
  never folded (`collapse: breaking` fails); a type in `exclude` stays out.
- Links, images and HTML written in a subject are neutralized (`<`, `>`, `](`
  as HTML entities): the text stays readable, nothing becomes clickable.
- The heading date is today, UTC.

## Example

Replace `<sha>` with the commit of a release tag ([Pin a release](../README.md#pin-a-release)).

```yaml
name: Release

on:
  push:
    tags: ["v*"]

permissions: {}

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: false # never stop a publication halfway

jobs:
  release:
    runs-on: ubuntu-latest
    permissions:
      contents: write # create the release
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 0
          persist-credentials: false
      - id: previous
        name: Find the previous release tag
        run: echo "tag=$(git describe --tags --abbrev=0 --match 'v[0-9]*' HEAD^)" >>"$GITHUB_OUTPUT"
      - id: changelog
        uses: wireapp/wire-rm-actions/changelog@<sha> # vX.Y.Z
        with:
          from-tag: ${{ steps.previous.outputs.tag }}
          to-ref: ${{ github.sha }}
          heading: "false"
          output-file: ${{ runner.temp }}/changelog.md
      - name: Create the release
        env:
          GH_TOKEN: ${{ github.token }}
          GH_REPO: ${{ github.repository }}
          TAG: ${{ github.ref_name }}
          NOTES: ${{ steps.changelog.outputs.file }}
        run: gh release create "$TAG" --verify-tag --title "$TAG" --notes-file "$NOTES"
```

## Design notes

**The commit history is the changelog.** Conventional commit messages already
say what changed and why it matters: the changelog reads them, so nobody
writes the same thing twice and nothing is forgotten.

**Continuity over novelty.** The format is the one components have published
for years (generate-changelog 1.8.0), down to the section names and the link style:
readers and tools that know it keep working.

**No toolchain for a text file.** Bash, git and awk, present on every runner:
no Node, no package, nothing to pin or to update for a changelog.

**Commit subjects are untrusted input.** Anyone who gets a commit merged
writes a line of the release notes: what they write stays text, and never
becomes a link, an image or HTML on the release page.
