[wire-rm-actions](../README.md) ·
[version](../version/README.md) ·
[build-image](../build-image/README.md) ·
[quay-login](../quay-login/README.md) ·
**publish-chart** ·
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

# publish-chart

> Push a Helm chart to the Wire OCI layout, never overwriting a version that
> is already published: packaged from a chart directory at the build version,
> or an already packaged `.tgz` pushed as is at publication.

## Definition

`publish-chart` sets both the chart `version` and `appVersion` to the build
version (ADR-0018), whatever `Chart.yaml` says, and pushes the package to
`oci://<registry>/wire/charts/<channel>/<name>` (ADR-0012). It outputs the
repository and the digest, ready for
[notify-rm](../notify-rm/README.md).

At publication, the chart is the `.tgz` asset of the draft release, the exact
package that was prepared and approved: `chart-file` pushes it as is, without
repackaging and never with an expiration. The same content already under that
version is a no-op, another content a failure.

## Technical reference

### Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `chart-path` | one of the two | | Path of the chart directory to package. |
| `chart-file` | one of the two | | Path of a packaged chart, `<name>-<version>.tgz`, pushed as is. |
| `version` | with `chart-path` | | The version, from [version](../version/README.md); with `chart-file`, checked against the package when given. |
| `chart-name` | no | the `Chart.yaml` name | Chart name in the registry (checked against the package with `chart-file`). |
| `registry` | no | `quay.io` | OCI registry host. |
| `channel` | no | `dev` | Registry channel: `dev` or `stable`. |
| `expires-after` | no | `""` | Dev channel and `chart-path` only: Quay deletes the version after this delay (`90d`, or hours `h`, days `d`, weeks `w`). Empty keeps it. |
| `attempts` | no | `1` | `chart-file` only: how many times the push is tried, 10 s apart (`1` does not retry). The presence check runs again before each attempt, as Quay has answered `500` on a manifest PUT that was committed. |
| `username` | no | `""` | Registry user (a Quay robot account); empty when the job is already logged in ([quay-login](../quay-login/README.md)). |
| `password` | no | `""` | Registry password or token, with `username`. |

### Outputs

| Output | Example | Description |
|---|---|---|
| `repository` | `oci://quay.io/wire/charts/dev/my-component` | Where the chart lives. |
| `digest` | `sha256:4f1c…` | Digest of the published chart manifest. |
| `status` | `pushed` | `pushed`, or `present` when the version was already in the registry. |

### Requirements

- Helm 3.8 or later on `PATH` (`azure/setup-helm`).
- Write access to `<registry>/wire/charts/<channel>/<name>`: a login done
  before (`helm registry login`, [quay-login](../quay-login/README.md)) or
  `username` and `password`.
- With `expires-after`: `oras` (`oras-project/setup-oras`) and `jq` on `PATH`.
- Images pushed **before** this step: the chart template defaults the image
  tag to `.Chart.AppVersion` (or `.Chart.Version`), which must exist.

### Behaviour

1. Logs in to the registry when a user is given, the password on stdin.
2. If the version is already in the registry: nothing is pushed, the existing
   digest is read back. With `chart-file`, the pulled package must have the
   sha256 of the given one: another content fails the step.
3. Otherwise, with `chart-path`: `helm dependency build` when `Chart.yaml` has
   dependencies, `helm package --version <version> --app-version <version>`,
   `helm push`. With `chart-file`: `helm push` of the file as is, after
   checking its name, its `version == appVersion` and, when given, `version`
   and `chart-name`. When the push fails and `attempts` allows another, the
   step waits 10 s and starts again from point 2: a chart that landed despite
   the error is a no-op (same sha256) or a failure (another content), never
   pushed twice. The step fails when the last attempt fails.
4. With `expires-after`, the pushed manifest gets the `quay.expires-after`
   annotation (rewritten with `oras`, as `helm push` cannot set it), and the
   digest output is that of the annotated manifest. A `stable` chart never
   expires: the input fails on any other channel.
5. Logs out of the registry when this action logged in, also when a previous
   step failed.

A push that returns no `sha256:` digest fails the step.

## Example

Replace `<sha>` with the commit of a release tag ([Pin a release](../README.md#pin-a-release)).

```yaml
name: Dev build

on:
  push:
    branches: [dev]

permissions: {}

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: false # never stop a publication halfway

jobs:
  chart:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 0
          persist-credentials: false
      - uses: azure/setup-helm@9bc31f4ebc9c6b171d7bfbaa5d006ae7abdb4310 # v5.0.1
        with:
          version: v4.3.0
      - id: version
        uses: wireapp/wire-rm-actions/version@<sha> # vX.Y.Z
      # Push the images first, e.g. with build-image at steps.version.outputs.version.
      - id: chart
        uses: wireapp/wire-rm-actions/publish-chart@<sha> # vX.Y.Z
        with:
          chart-path: charts/my-chart
          version: ${{ steps.version.outputs.version }}
          expires-after: 90d
          username: ${{ secrets.QUAY_USER }}
          password: ${{ secrets.QUAY_TOKEN }}
      - name: Show the chart
        env:
          REPOSITORY: ${{ steps.chart.outputs.repository }}
          DIGEST: ${{ steps.chart.outputs.digest }}
        run: echo "$REPOSITORY@$DIGEST"
```

`expires-after` needs `oras` on `PATH`: add `oras-project/setup-oras`, pinned
by SHA, before this step, or drop the input.

At publication, after [quay-login](../quay-login/README.md) and the download
of the draft assets:

```yaml
      - id: chart
        uses: wireapp/wire-rm-actions/publish-chart@<sha> # vX.Y.Z
        with:
          chart-file: ${{ steps.manifest.outputs.chart-path }}
          version: ${{ steps.manifest.outputs.version }}
          channel: stable
```

## Design notes

**A published version is immutable.** Once `my-chart:5.2.2-…` exists, it
always means the same bytes: a rerun of the same commit reads the digest back
instead of pushing again. Deployments, the release manager and audits can all
rely on a version and a digest that never move.

**The chart and its image are one thing.** `version == appVersion == image
tag`: installing chart `X` installs image `X`. Nobody maintains a mapping, and
`Chart.yaml` can keep a placeholder version.

**Channels keep dev builds apart.** Dev builds go to `wire/charts/dev`,
releases to `wire/charts/stable`: a consumer of stable charts never sees a dev
build by mistake, and dev builds can expire without touching releases.

**The published chart is the approved package.** A release pushes the `.tgz`
that was prepared, verified against the manifest and approved, byte for byte:
repackaging at publication would produce another artifact than the one the
release manager approved.

**Credentials stay short-lived.** The password reaches Helm on stdin, never on
a command line, and the action logs out when done, so the later steps of the
job never find it in the Helm registry config.
