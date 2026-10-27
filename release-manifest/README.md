[wire-rm-actions](../README.md) ·
[version](../version/README.md) ·
[build-image](../build-image/README.md) ·
[quay-login](../quay-login/README.md) ·
[publish-chart](../publish-chart/README.md) ·
[notify-rm](../notify-rm/README.md) ·
[changelog](../changelog/README.md) ·
[release-declaration](../release-declaration/README.md) ·
[release-documents](../release-documents/README.md) ·
**release-manifest** ·
[compatibility](../compatibility/README.md) ·
[release-inputs](../release-inputs/README.md) ·
[release-source](../release-source/README.md) ·
[promote-image](../promote-image/README.md) ·
[ci-gate](../ci-gate/README.md) ·
[draft-release](../draft-release/README.md) ·
[publish-chart-s3](../publish-chart-s3/README.md)

# release-manifest

> Write, verify and complete the release manifest of a build: what was built,
> from which commit, what it provides and requires.

## Definition

The release manifest (ADR-0020 §2, `wire.component-release-manifest/v1alpha1`)
is the JSON record of one build: the source commit, the image and the chart
with their digests, the `compatibility` block derived from the component's
`publication/compatibility.yaml` (ADR-0020: `providesApis`, `consumesApis`,
`dependsOn`, `includes`, written as `provides`, `requires`, `includes` by
[compatibility](../compatibility/README.md)), the build run and the release
documents. The release manager derives the requirements and the
provided interfaces of a version from it.

| Mode | When | What |
|---|---|---|
| `write` | prepare (release) or dev build | Freezes the manifest; every required field is checked, nothing is written on error. |
| `verify` | publish, before anything is promoted | Checks the downloaded chart package and documents against their sha256, the version, the commit, the tag and the source branch; with `check-source-branch`, that the commit is still on that branch. |
| `complete` | publish, after promotion | Appends `publication` (date, run, digests); refuses to touch the frozen part; idempotent. |

A dev build (`release-type: dev`) has no tag, no candidate tag and no chart
file: its image and chart are identified by digest.

## Technical reference

### Inputs

| Input | Modes | Description |
|---|---|---|
| `mode` | all | `write`, `verify` or `complete`. |
| `manifest` | all | Path of the manifest (default `release-manifest.json`). |
| `component`, `version`, `release-type` | write | Component id, version, `ga`/`alpha`/`beta`/`rc`/`dev`. |
| `source-repository`, `source-ref`, `source-commit` | write | Where the build comes from (full commit sha). |
| `image-repository`, `image-digest`, `image-candidate-tag` | write | The image; the candidate tag for a release. |
| `chart-repository`, `chart-file`, `chart-sha256` | write | The chart package of a release. |
| `chart-digest` | write | The pushed chart of a dev build. |
| `compatibility-file` | write | Default empty: `publication/compatibility.yaml` (ADR-0020). Checked and converted by [compatibility](../compatibility/README.md); `includes` is written as `[]` when empty. |
| `documents-json` | write | The `documents-json` output of [release-documents](../release-documents/README.md). |
| `inputs-json` | write | The build inputs other than the source repository, e.g. the configuration repository: a JSON array of objects with a `name` (default `[]`), written as `inputs`. |
| `extra-artifacts-json` | write | The artifacts other than the image and the chart, e.g. a deployment bundle: a JSON array of `{type, file, sha256}` (default `[]`), appended after the chart. `type` is not `image` or `chart`, `file` a plain name, `sha256` hex. |
| `expires-after` | write | Dev builds only, e.g. `90d` (hours `h`, days `d`, weeks `w`): `expires_at` is the build date plus that delay (ADR-0020 §5). |
| `request-id`, `rm-origin` | write | The release manager request, empty on the manual path. |
| `tag-prefix` | write, verify | Prefix of the git tag (default `v`). |
| `version`, `source-commit`, `asset-dir`, `release-branches` | verify | Expected version and commit, where the assets are, the releasable branches. Every extra artifact must be in `asset-dir` with the sha256 of the manifest. |
| `check-source-branch` | verify | `true` or `false` (default `false`). When `true`, the source commit must still be an ancestor of `origin/<source ref>` (see below). |
| `run-url`, `digests-json`, `out` | complete | The publishing run, the published digests, another output path. |

### Outputs

`manifest` (write, complete); for verify: `version`, `kind`, `stage`, `type`,
`source-ref`, `source-commit`, `image-*`, `chart-*` (with `chart-path`),
`request-id`, `rm-origin`, `note-file`, `declaration-file`, and
`extra-artifacts-json`: the artifacts after the chart as a JSON array of
`{type, file, path, sha256}` (`[]` when there is none).

### Requirements

- `bash`, `jq` and `yq` (all GitHub-hosted Ubuntu runners).
- With `check-source-branch: true`, `git` and a checkout of the source branch
  with `fetch-depth: 0`, so that `origin/<source ref>` exists.

### Stale source check

With `check-source-branch: true`, once the manifest is verified, `verify`
refuses the candidate in two cases: `origin/<source ref>` is not in the
checkout (the branch was not fetched), or the prepared source commit is no
longer an ancestor of it (the branch was rewritten or moved elsewhere since
the candidate was prepared). A branch that merely moved forward is fine. The
source ref comes from the manifest, so the check belongs here and not before
the manifest is downloaded.

## Example

```yaml
      - id: manifest
        uses: wireapp/wire-rm-actions/release-manifest@<sha> # vX.Y.Z
        with:
          mode: write
          manifest: ${{ runner.temp }}/release/release-manifest.json
          component: my-component
          version: ${{ steps.version.outputs.version }}
          release-type: ${{ inputs.type }}
          source-repository: ${{ github.server_url }}/${{ github.repository }}
          source-ref: ${{ inputs.source_branch }}
          source-commit: ${{ steps.source.outputs.sha }}
          image-repository: quay.io/wire/my-component
          image-digest: ${{ steps.image.outputs.digest }}
          image-candidate-tag: ${{ steps.image.outputs.candidate-tag }}
          chart-repository: oci://quay.io/wire/charts/stable/my-component
          chart-file: ${{ steps.chart.outputs.file }}
          chart-sha256: ${{ steps.chart.outputs.sha256 }}
          documents-json: ${{ steps.documents.outputs.documents-json }}
```

Then `verify` in the publish job on the downloaded draft assets, after a
checkout of the source branch (`ref:` the manifest's `source.ref`,
`fetch-depth: 0`) with `check-source-branch: true`, and pass the
`complete` output to [notify-rm](../notify-rm/README.md) as
`release-manifest-file`.

## Design notes

**Frozen at preparation.** What is approved is what is published: the
manifest is written once, verified against the assets before anything moves,
and completion only appends.

**The three compatibility lists, always.** The release manager refuses a
manifest without `provides`, `requires` and `includes`; an absent `includes`
is written as `[]`. The ADR-0020 file is the source: the manifest keeps the
legacy shape the release manager reads today, the conversion lives in one
place ([compatibility](../compatibility/README.md)).
