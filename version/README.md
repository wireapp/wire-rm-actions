[wire-rm-actions](../README.md) ·
**version** ·
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
[release-source](../release-source/README.md) ·
[promote-image](../promote-image/README.md) ·
[ci-gate](../ci-gate/README.md) ·
[draft-release](../draft-release/README.md) ·
[publish-chart-s3](../publish-chart-s3/README.md)

# version

> The version of a build: the tag itself on a tag build, otherwise a dev build
> derived from the nearest release tag. Or, in release mode, the next release
> version of a branch. Git is the only input.

## Definition

`version` gives every build of a component one version (ADR-0018), shared by
its images, its chart and its release manager record. A tag build is the tag;
any other build is a SemVer pre-release of the next version, built from the
commit date and SHA, so that it sorts above the last release and below the
next one.

| Build | Nearest tag | Version |
|---|---|---|
| tag `v5.2.1` | | `5.2.1` (kind `ga`) |
| tag `v5.3.0-rc.1` | | `5.3.0-rc.1` (kind `prerelease`) |
| dev/release branch | GA `v5.2.1` | `5.2.2-20260930120000.gabcdef0` |
| other branch | GA `v5.2.1` | `5.2.2-20260930120000.my-feature.gabcdef0` |
| dev/release branch | pre `v5.3.0-rc.1` | `5.3.0-rc.1.20260930120000.gabcdef0` |
| other branch | pre `v5.3.0-rc.1` | `5.3.0-rc.1.20260930120000.my-feature.gabcdef0` |

In **release mode** (`mode: release`), a prepare-release workflow asks for the
next explicit version of a branch, from the release tags reachable from it:

| Latest release reachable | Type | Bump | Version |
|---|---|---|---|
| GA `v5.2.1` | `ga` | `patch` | `5.2.2` |
| GA `v5.2.1` | `ga` | `minor` | `5.3.0` |
| GA `v5.2.1` | `rc` | `minor` | `5.3.0-rc.1` |
| pre `v5.3.0-rc.1` | `rc` | | `5.3.0-rc.2` |
| pre `v5.3.0-beta.2` | `rc` | | `5.3.0-rc.1` |
| pre `v5.3.0-rc.1` | `ga` | `patch` | `5.3.0` |
| pre `v5.3.0-rc.1` | `beta` | `patch` | refused: a channel never goes backward |
| pre `v5.3.0-rc.1` | `alpha` | `minor` | `5.4.0-alpha.1`: a new line opens, `rc.1` stays unpromoted |
| pre `v5.3.0-rc.1` | `ga` | `major` | `6.0.0` |

## Technical reference

### Inputs

| Input | Mode | Default | Description |
|---|---|---|---|
| `mode` | | `build` | `build` or `release`. |
| `tag-prefix` | both | `v` | Prefix of the release tags; `""` for none. |
| `release-branches` | build | `^(dev\|develop\|release/.+\|release-.+)$` | Regex of the branches whose versions carry no `<branch>` identifier. |
| `source-branch` | release | required | The branch to release from, the trunk or a `release/X.Y` line, read as `<remote>/<branch>`. |
| `release-type` | release | required | `ga`, `alpha`, `beta` or `rc`. |
| `version-bump` | release | `patch` | `patch`, `minor` or `major`. From a GA, the bump of the next GA or of the first pre-release; from a pre-release, `patch` continues it and `minor` or `major` open a new line from its base. |
| `expected-version` | release | `""` | The version the release manager previewed: the step fails when it differs from the result, never adopts it. |
| `remote` | release | `origin` | The git remote holding the source branch. |

### Outputs

| Output | Example | Description |
|---|---|---|
| `version` | `5.2.2-20260930120000.gabcdef0` | The version. |
| `kind` | `dev` | `dev`, `ga` or `prerelease`. |
| `base-tag` | `v5.2.1` | The tag the version derives from (the tag itself on a tag build; the latest release reachable from the branch in release mode). |
| `sha` | `abcdef0…` | The full commit SHA (the head of the source branch in release mode). |
| `tag` | `v5.2.2` | Release mode: the tag the publication will create. |
| `from-tag` | `v5.2.1` | Release mode: the changelog base, the preceding GA for a GA or a first pre-release, the latest release otherwise. |

### Requirements

- `actions/checkout` with `fetch-depth: 0` (history and tags) for a dev build:
  a shallow clone fails.
- At least one source tag reachable from the commit: `<prefix>X.Y.Z` (GA) or
  `<prefix>X.Y.Z-alpha.N`, `-beta.N`, `-rc.N` with `N` from 1 (pre-release).
  Tags of another form (`v1.2.3-alpha04`, `v1.2.3-pre.3`) are skipped.
- `bash`, `git` and GNU `sort` (`ubuntu-latest`).

### Behaviour

- **Tag build** (`github.ref_type == tag`): the version is the tag without its
  prefix. A tag that is neither GA nor pre-release fails the step.
- **Dev build**: the branch is `github.head_ref` on a pull request, else the
  pushed branch.
  - The nearest source tag comes from `git describe`. When several tags point
    to that commit (`rc.2`, then the GA), the highest wins, a GA above any
    pre-release.
  - `<ts>` is the committer date in UTC, `YYYYMMDDHHMMSS`, and `<sha7>` the
    first 7 characters of the commit.
  - Outside `release-branches`, `<branch>` is the last segment of the branch
    name, lowercased, every other character replaced by `-`, cut to 14
    characters, trailing `-` removed. A numeric segment with a leading zero
    (`feat/0123`) is not valid SemVer and fails.
- A version longer than 63 characters (the Helm limit) fails.
- **Release mode**: the anchor is the latest release tag reachable from
  `<remote>/<source-branch>` (the highest when several point to the same
  commit); the rules of the table above apply. A
  `release/X.Y` branch may only produce `X.Y.*`; the target must not exist as
  a tag, and no release of the scanned scope (the line, or every release for
  the trunk) may be ahead of it. The former pre-release form `X.Y.Z-rc04` is
  read but never continued, since `rc.5` sorts below `rc04` in SemVer.

## Example

Replace `<sha>` with the commit of a release tag ([Pin a release](../README.md#pin-a-release)).

```yaml
name: Build

on:
  push:
    branches: [dev]
    tags: ["v*"]

permissions: {}

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: false # never stop a publication halfway

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 0
          persist-credentials: false
      - id: version
        uses: wireapp/wire-rm-actions/version@<sha> # vX.Y.Z
      - name: Show the version
        env:
          VERSION: ${{ steps.version.outputs.version }}
          KIND: ${{ steps.version.outputs.kind }}
        run: echo "Building $VERSION ($KIND)"
```

In a prepare-release workflow, after a checkout with `fetch-depth: 0`:

```yaml
      - id: version
        uses: wireapp/wire-rm-actions/version@<sha> # vX.Y.Z
        with:
          mode: release
          source-branch: ${{ inputs.source_branch }}
          release-type: ${{ inputs.type }}
          version-bump: ${{ inputs.version_bump }}
          expected-version: ${{ inputs.expected_version }}
```

## Design notes

**One version, everywhere.** The image tag, the chart `version`, the chart
`appVersion` and the release manager record carry the same string. Nobody has
to map one to another, and a running pod tells you which commit it came from.

**Git is the only source of truth.** No counter, no file to bump, no API to
call: the same commit always gives the same version, on a laptop or in CI. The
timestamp is the committer date, not the build time, so a rerun gives the
same version too.

**SemVer ordering does the work.** A dev build is a pre-release of the *next*
patch (`5.2.2-…` after `5.2.1`): any tool that sorts SemVer puts it after the
release it starts from, and before the release that will follow. Feature
branches add their name, so two branches built in the same second never share
a version.

**Fail rather than guess.** No tag, a shallow clone, a malformed tag, a
version too long for Helm: the step fails with the reason, instead of
publishing a version nobody can trace back.
