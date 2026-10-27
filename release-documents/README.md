[wire-rm-actions](../README.md) ·
[version](../version/README.md) ·
[build-image](../build-image/README.md) ·
[quay-login](../quay-login/README.md) ·
[publish-chart](../publish-chart/README.md) ·
[notify-rm](../notify-rm/README.md) ·
[changelog](../changelog/README.md) ·
[release-declaration](../release-declaration/README.md) ·
**release-documents** ·
[release-manifest](../release-manifest/README.md) ·
[compatibility](../compatibility/README.md) ·
[release-inputs](../release-inputs/README.md) ·
[release-source](../release-source/README.md) ·
[promote-image](../promote-image/README.md) ·
[ci-gate](../ci-gate/README.md) ·
[draft-release](../draft-release/README.md) ·
[publish-chart-s3](../publish-chart-s3/README.md)

# release-documents

> Gather the release note and the release declaration of a release or a dev
> build, and the `documents` object of its release manifest.

## Definition

Every release carries two documents written ahead in the repository (ADR-0020
§2 and §3): the release note, what a reader learns about the version, and the
release declaration, what an operator must know before upgrading.
`release-documents` finds them, checks them and hands them to
[release-manifest](../release-manifest/README.md) and to the draft GitHub
Release.

| Build | Release note | Release declaration |
|---|---|---|
| `ga` | required, copied to `<out-dir>/release-note.md` | required, written to `<out-dir>/release-declaration.json` |
| `alpha`, `beta`, `rc` | optional (warning), copied | optional, written |
| `dev` | optional (warning), referenced by its repository path | never |

Both live in `publication/` (ADR-0020): `publication/release-note.md`, the
note of the version the build leads to, and `publication/declaration.json`
(schema `wire.component-release/v1alpha2`), the declaration of that GA, which
its pre-releases share. The declaration is the `release-declaration` input
(sent by the release manager, kept byte for byte), else
`publication/declaration.json` in canonical JSON, validated with
[release-declaration](../release-declaration/README.md) with the component
and the base version (`1.41.5` for `1.41.5-rc.1`).

## Technical reference

### Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `component` | yes | | Component id the declaration must declare. |
| `version` | yes | | The version, without `v`. |
| `release-type` | yes | | `ga`, `alpha`, `beta`, `rc` or `dev`. |
| `release-note` | no | `""` | The `release_note` dispatch input. |
| `note-input` | no | `ignore` | `ignore`: the repository note wins, the input only warns. `override`: the input replaces the repository note of a release. |
| `release-declaration` | no | `""` | JSON text of the declaration; empty reads the repository file. |
| `publication-dir` | no | `publication` | Folder of `release-note.md` and `declaration.json`, read first. |
| `out-dir` | no | `.` | Where the release documents are written. |

### Outputs

| Output | Description |
|---|---|
| `documents-json` | The `documents` object of the manifest, `{}` when empty. |
| `note-file`, `note-path`, `note-sha256`, `note-source` | The note: file name (or repository path for a dev build), path found, sha256, `repository` or `input`. |
| `declaration-file`, `declaration-sha256`, `declaration-source` | The declaration: `release-declaration.json`, sha256, `release_manager` or `repository`. |

### Requirements

- `bash` and `jq` (all GitHub-hosted runners); a checkout of the source commit.

## Example

```yaml
      - id: documents
        uses: wireapp/wire-rm-actions/release-documents@<sha> # vX.Y.Z
        with:
          component: my-component
          version: ${{ steps.version.outputs.version }}
          release-type: ${{ inputs.type }}
          release-declaration: ${{ inputs.release_declaration }}
          out-dir: ${{ runner.temp }}/release
```

## Design notes

**Written ahead, read at the source commit.** The note and the declaration are
reviewed in a pull request like the code they describe, so a release never
waits for someone to write them, and a GA without them does not start.

**Dev builds warn early.** A dev build attaches the note of the version it
leads to and warns when there is none: the missing note shows weeks before the
GA, not on release day.
