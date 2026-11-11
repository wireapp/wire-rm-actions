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
[publish-chart-s3](../publish-chart-s3/README.md) ·
**publish-extra-chart**

# publish-extra-chart

> Push an extra chart, one that repackages an upstream release, to the Wire
> OCI layout with its own version and appVersion, never overwriting a version
> that is already published.

## Definition

Wire charts go through [publish-chart](../publish-chart/README.md), where the
chart `version` and `appVersion` are the same build version (ADR-0018). Extra
charts do not fit that rule: a wrapper of cert-manager, keycloakx or loki
names the upstream release in its `appVersion`, maintained by hand, while its
own `version` comes from the [version](../version/README.md) action.

`publish-extra-chart` packages the chart directory with `version` set to the
build version and `appVersion` to `app-version`, then pushes it to
`oci://<registry>/wire/charts/<channel>/<name>` (ADR-0012), with the same
guarantees as publish-chart: a published version is never overwritten, its
digest is read back, and a dev chart can expire on Quay.

## Technical reference

### Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `chart-path` | yes | | Path of the chart directory to package. |
| `version` | yes | | The chart version, from [version](../version/README.md). |
| `app-version` | yes | | The `appVersion` of the package: the upstream release, usually read from `Chart.yaml`. |
| `chart-name` | no | the `Chart.yaml` name | Chart name in the registry. |
| `registry` | no | `quay.io` | OCI registry host. |
| `channel` | no | `dev` | Registry channel: `dev` or `stable`. |
| `expires-after` | no | `""` | Dev channel only: Quay deletes the version after this delay (`90d`, or hours `h`, days `d`, weeks `w`). Empty keeps it. |
| `username` | no | `""` | Registry user (a Quay robot account); empty when the job is already logged in ([quay-login](../quay-login/README.md)). |
| `password` | no | `""` | Registry password or token, with `username`. |

### Outputs

Same as publish-chart: `repository`, `digest`, and `status` (`pushed`, or
`present` when the version was already in the registry).

### Requirements

- Helm 3.8 or later on `PATH` (`azure/setup-helm`).
- Write access to `<registry>/wire/charts/<channel>/<name>`.
- With `expires-after`: `oras` (`oras-project/setup-oras`) and `jq` on `PATH`.

### Behaviour

The steps of publish-chart with `chart-path`, the package made with
`helm package --version <version> --app-version <app-version>`. There is no
`chart-file` mode: an extra chart is packaged where it is published.

## Example

```yaml
      - name: Read the upstream release of the chart
        id: chart
        run: echo "app-version=$(yq '.appVersion // ""' charts/loki-wrapper/Chart.yaml)" >>"$GITHUB_OUTPUT"

      - uses: wireapp/wire-rm-actions/publish-extra-chart@<sha> # vX.Y.Z
        with:
          chart-path: charts/loki-wrapper
          version: ${{ steps.version.outputs.version }}
          app-version: ${{ steps.chart.outputs.app-version || steps.version.outputs.version }}
          channel: dev
          expires-after: 90d
          username: ${{ steps.quay.outputs.username }}
          password: ${{ steps.quay.outputs.token }}
```

## Why

**A separate action, not an option of publish-chart.** `version ==
appVersion` stays a hard rule for Wire charts: nothing in publish-chart can
turn it off. Choosing this action is the visible, reviewable exception, kept
to charts that only repackage an upstream release.
