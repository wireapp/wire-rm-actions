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
**release-inputs** ·
[release-source](../release-source/README.md) ·
[promote-image](../promote-image/README.md) ·
[ci-gate](../ci-gate/README.md) ·
[draft-release](../draft-release/README.md) ·
[publish-chart-s3](../publish-chart-s3/README.md)

# release-inputs

> Validate the dispatch inputs of a prepare-release or publish-release
> workflow before anything else runs: a bad input fails the run with its
> reason, and nothing has happened yet.

## Definition

A release is prepared by a `workflow_dispatch` carrying nine inputs (ADR-0021
section 1), typed by hand or sent by the release manager. `release-inputs`
checks each of them, the pairs that go together (`request-id` with
`rm-origin`), and their total size against the 60 000 character budget the
release manager applies. It runs before the checkout, so an invalid input
costs a few seconds and leaves no trace.

| Mode | When | What |
|---|---|---|
| `prepare` (default) | prepare-release | The nine inputs of the dispatch, and their size. |
| `publish` | publish-release | `version`, `release-id`, `request-id` and `rm-origin`: the inputs of the recovery path, typed by hand, that end up in a tag name and an API path. |

## Technical reference

### Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `mode` | no | `prepare` | `prepare` or `publish`. |
| `source-branch` | prepare | `""` | Branch to release from; must match `source-branches`. |
| `type` | prepare | `""` | `ga`, `alpha`, `beta` or `rc`. |
| `version-bump` | prepare | `""` | `patch`, `minor` or `major`. |
| `force` | no | `""` | prepare: `true` or `false`; empty means `false`. |
| `version` | publish | `""` | `X.Y.Z` or `X.Y.Z-<alpha\|beta\|rc>.N`. |
| `release-id` | no | `""` | publish: numeric id of the draft release; empty to find it by version. |
| `request-id` | no | `""` | Release manager request (lower-case UUID4); empty on a manual run. |
| `expected-version` | no | `""` | prepare: the version the release manager previewed; checked by [version](../version/README.md). |
| `release-note` | no | `""` | prepare: release note text; only its size is checked here. |
| `release-declaration` | no | `""` | prepare: JSON text of the declaration; only its shape (an object) is checked here. |
| `rm-origin` | no | `""` | `staging`, `prod` or `local` (a developer's release manager, accepted with a warning); required with `request-id`, refused without. |
| `source-branches` | no | `^(dev\|release/[0-9]+\.[0-9]+)$` | prepare: regex of the releasable branches. |

### Outputs

| Output | Example | Description |
|---|---|---|
| `rm-driven` | `true` | `true` when the run comes from a release manager request. |
| `force` | `false` | prepare only: the normalized flag; empty in `publish`. |
| `release-type` | `rc` | prepare: the validated type. publish: derived from the version, `ga` without a suffix, else `alpha`, `beta` or `rc`. |

### Requirements

- `bash` and `jq`. No checkout needed.

## Example

```yaml
jobs:
  prepare:
    runs-on: ubuntu-latest
    steps:
      - id: inputs
        uses: wireapp/wire-rm-actions/release-inputs@<sha> # vX.Y.Z
        with:
          source-branch: ${{ inputs.source_branch }}
          type: ${{ inputs.type }}
          version-bump: ${{ inputs.version_bump }}
          force: ${{ inputs.force }}
          request-id: ${{ inputs.request_id }}
          expected-version: ${{ inputs.expected_version }}
          release-note: ${{ inputs.release_note }}
          release-declaration: ${{ inputs.release_declaration }}
          rm-origin: ${{ inputs.rm_origin }}
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 0
          persist-credentials: false
```

The publish-release workflow, which has no size budget to respect:

```yaml
      - id: inputs
        uses: wireapp/wire-rm-actions/release-inputs@<sha> # vX.Y.Z
        with:
          mode: publish
          version: ${{ inputs.version }}
          release-id: ${{ inputs.release_id }}
          request-id: ${{ inputs.request_id }}
          rm-origin: ${{ inputs.rm_origin }}
```

## Design notes

**Free text is checked before it builds anything.** The inputs end up in tag
names, API paths and files: each one is matched against its grammar first, so
nothing downstream has to defend itself.

**Publish checks the same grammars, no budget.** `version`, `release-id`,
`request-id` and `rm-origin` are short and typed by hand on the recovery path;
the budget only guards the free text of a preparation.

**Same budget as the release manager.** The release manager refuses a request
above 60 000 characters before dispatching; a manual run gets the same limit,
counted in characters, so both paths behave alike.
