[wire-rm-actions](../README.md) ·
[version](../version/README.md) ·
[build-image](../build-image/README.md) ·
[quay-login](../quay-login/README.md) ·
[publish-chart](../publish-chart/README.md) ·
[notify-rm](../notify-rm/README.md) ·
[changelog](../changelog/README.md) ·
[release-declaration](../release-declaration/README.md) ·
[release-documents](../release-documents/README.md) ·
[release-manifest](../release-manifest/README.md) ·
[compatibility](../compatibility/README.md) ·
[release-inputs](../release-inputs/README.md) ·
**release-source** ·
[promote-image](../promote-image/README.md) ·
[ci-gate](../ci-gate/README.md) ·
[draft-release](../draft-release/README.md) ·
[publish-chart-s3](../publish-chart-s3/README.md)

# release-source

> The source of a release candidate: the branch exists, the commit is
> recorded, the run says what it is preparing.

## Definition

A candidate is built from one commit of one branch. `release-source` covers
the three moments of a prepare-release workflow where that source matters:
before the checkout, right after it, and once the version is known.

| Mode | When | What |
|---|---|---|
| `verify` | before the checkout | The branch exists on the repository. When it does not, the job summary names it and lists the `release/*` branches that exist, and the run fails. |
| `resolve` | after `actions/checkout` at the branch, `fetch-depth: 0` | The checkout is at the tip of `origin/<branch>`; outputs its commit. |
| `summary` | once the version is known | Writes the identity of the candidate to the job summary: version, channel, branch, commit, anchor tag, and the commits since the previous release. |

## Technical reference

### Inputs

| Input | Modes | Description |
|---|---|---|
| `mode` | all | `verify`, `resolve` or `summary`. |
| `source-branch` | all | The branch to release from, `[A-Za-z0-9._/-]+`: it reaches an API path and a git ref, so nothing else is accepted. |
| `repository`, `token` | verify | `owner/name` and a token with read access; default `github.repository` and `github.token`. |
| `version`, `release-type` | summary | The version without the tag prefix, and its channel (`ga`, `alpha`, `beta`, `rc`). |
| `source-sha` | summary | The full sha, the `sha` output of `resolve`. |
| `base-tag`, `from-tag` | summary | The latest release tag reachable (the anchor) and the tag the changes are counted from. |
| `tag-prefix` | summary | Shown before the version (default `v`). |
| `note` | summary | A trailing line of the summary (default none). |
| `commits` | summary | `true` (default) lists the commits `from-tag..source-sha`, `_No commits since <tag>._` when there is none; `false` leaves the list out. |

### Outputs

| Output | Mode | Description |
|---|---|---|
| `sha` | resolve | The full sha of the source commit. |
| `commit-count` | summary | The number of commits since `from-tag`. |

### Requirements

- `bash`; `gh` for `verify` (GitHub-hosted runners), `git` and the checkout
  with `fetch-depth: 0` for `resolve` and `summary`.
- Token permissions: `contents: read`.

## Example

```yaml
      - uses: wireapp/wire-rm-actions/release-source@<sha> # vX.Y.Z
        with:
          mode: verify
          source-branch: ${{ inputs.source_branch }}
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          ref: ${{ inputs.source_branch }}
          fetch-depth: 0
          persist-credentials: false
      - id: source
        uses: wireapp/wire-rm-actions/release-source@<sha> # vX.Y.Z
        with:
          mode: resolve
          source-branch: ${{ inputs.source_branch }}
      - id: version
        uses: wireapp/wire-rm-actions/version@<sha> # vX.Y.Z
        with:
          mode: release
          source-branch: ${{ inputs.source_branch }}
          release-type: ${{ inputs.type }}
          version-bump: ${{ inputs.version_bump }}
      - uses: wireapp/wire-rm-actions/release-source@<sha> # vX.Y.Z
        with:
          mode: summary
          source-branch: ${{ inputs.source_branch }}
          version: ${{ steps.version.outputs.version }}
          release-type: ${{ inputs.type }}
          source-sha: ${{ steps.source.outputs.sha }}
          base-tag: ${{ steps.version.outputs.base-tag }}
          from-tag: ${{ steps.version.outputs.from-tag }}
          note: Building the candidate image and packaging the chart.
```

## Design notes

**`verify` fails before anything is checked out.** A mistyped branch costs a
few seconds, and the summary says which release lines exist so the next
dispatch can be right.

**`resolve` pins the commit, not the branch.** The commit is recorded right
after the checkout and passed on: a later push to the branch must not change
what the candidate is built from. A checkout that is not at the tip of
`origin/<branch>` is refused, because the commit would then not be what the
branch says.

**The summary is written early.** The run's Summary page identifies the
candidate while preparation is still in progress; the draft release link is
added by [draft-release](../draft-release/README.md) once it exists.
