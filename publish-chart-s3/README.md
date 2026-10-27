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
[release-source](../release-source/README.md) ·
[promote-image](../promote-image/README.md) ·
[ci-gate](../ci-gate/README.md) ·
[draft-release](../draft-release/README.md) ·
**publish-chart-s3**

# publish-chart-s3

> Interim: push a packaged chart to an S3 Helm repository, for the
> deployments that still read one, never overwriting a published version.

## Definition

`publish-chart-s3` pushes the packaged chart a release already published to
`oci://quay.io/wire/charts/<channel>/<name>` ([publish-chart](../publish-chart/README.md))
to an S3 Helm repository as well, with the
[helm-s3](https://github.com/hypnoglow/helm-s3) plugin. Some deployments
still read `s3://public.wire.com/<repository>`; the
action keeps them fed until they read the OCI charts, and is removed then.

The same package already under that version is a no-op, another content a
failure: a version in the repository always means the same bytes.

## Technical reference

### Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `chart-file` | yes | | Path of the packaged chart, `<name>-<version>.tgz` (the name and version of its `Chart.yaml`). |
| `s3-repository` | yes | | Repository name, e.g. `charts-develop`, `charts-master`, `charts-extra`. |
| `s3-url` | no | `s3://public.wire.com/<s3-repository>` | Repository URL. |
| `helm-s3-version` | no | `0.15.1` | helm-s3 plugin version, installed when missing. |
| `aws-access-key-id` | yes | | AWS access key id with write access to the bucket. |
| `aws-secret-access-key` | yes | | AWS secret access key. |
| `aws-region` | no | `""` | AWS region of the bucket; empty lets helm-s3 find it. |

### Outputs

| Output | Example | Description |
|---|---|---|
| `name` | `my-component` | Chart name. |
| `version` | `2.0.17` | Chart version. |
| `repository` | `s3://public.wire.com/charts-master` | The repository URL. |
| `status` | `pushed` | `pushed`, or `present` when the same package was already there. |

### Requirements

- Helm 3.8 or later (`azure/setup-helm`) and `jq` on `PATH`.
- AWS credentials with write access to the bucket.

### Behaviour

1. Checks the inputs, reads the name and version of the package, and refuses
   a file not named `<name>-<version>.tgz`.
2. Installs helm-s3 when missing, adds and updates the repository.
3. If the version is in the repository (exact name and version, read as
   JSON): pulls it and compares the sha256. The same package is `present`,
   another content fails the step.
4. Otherwise `helm s3 push --relative`, never `--force`.

## Example

After the publication of a release, the chart being the asset of the draft
release. Replace `<sha>` with the commit of a release tag
([Pin a release](../README.md#pin-a-release)).

```yaml
      - uses: wireapp/wire-rm-actions/publish-chart-s3@<sha> # vX.Y.Z
        with:
          chart-file: ${{ steps.manifest.outputs.chart-path }}
          s3-repository: ${{ steps.manifest.outputs.kind == 'ga' && 'charts-master' || 'charts-develop' }}
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: ${{ secrets.AWS_REGION }}
```

## Design notes

**Interim by design.** The OCI chart is the reference; this push only feeds
the readers that have not moved yet. It runs last, after the publication and
the declaration to the release managers, so that a failure here never blocks
a release.

**Never overwrite.** `--force` would let a rerun silently replace a published
chart; the sha256 comparison makes a rerun safe and a conflicting content
loud.

**One copy.** Components each carried their own script for this;
this action replaces them.
