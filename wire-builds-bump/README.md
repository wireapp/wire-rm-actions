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
**wire-builds-bump**

# wire-builds-bump

> Point the wire-builds entry of a chart at a published version, in one
> commit. Already there: nothing to do. Another commit landed meanwhile: read
> again, apply again.

## Definition

The deployments built from [wire-builds](https://github.com/wireapp/wire-builds)
read `build.json`: one `helmCharts.<chart>` entry per chart (`repo`, `version`,
`meta`) and a top-level `version` that each change bumps. Each component used
to write that bump by hand, with a clone, a `jq` call and a push. This action
does it through the contents API: it sets `version`, `repo` and the `meta`
fields of the chart, bumps the pre-release of the top-level version, and
commits with a compare-and-swap on the blob sha, so a concurrent commit is
never overwritten.

## Technical reference

### Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `chart` | yes | | The `helmCharts` key of the chart. |
| `version` | yes | | The chart version. |
| `chart-repo` | no | the current one | The chart repository URL; required for a chart not yet in `build.json`. |
| `app-version` | no | `version` | `meta.appVersion`; `-` leaves it out. |
| `commit` | no | `""` | `meta.commit`, the full sha the version was built from; empty leaves it out. |
| `commit-url` | no | `<server>/<source-repository>/commit/<commit>` | `meta.commitURL`. |
| `source-repository` | no | `github.repository` | For the default `commit-url`. |
| `wire-builds-repository`, `branch`, `file` | no | `wireapp/wire-builds`, `dev`, `build.json` | Where the file is. |
| `message` | no | `Bump <chart> to <version>` | Commit message. |
| `bump-build-version` | no | `true` | Bumps the last number of the top-level pre-release (`1.0.0-zulu.5897` to `1.0.0-zulu.5898`). |
| `attempts` | no | `5` | How many times the commit is tried, 5 s apart. |
| `token` | yes | | `contents: write` on wire-builds, e.g. a fine-grained token or a GitHub App token; never the job's own token, which cannot write there. |

### Outputs

| Output | Example | Description |
|---|---|---|
| `status` | `bumped` | `bumped`, or `unchanged` when the entry already had the version, repo and meta fields. |
| `build-version` | `1.0.0-zulu.5898` | The top-level version after the step. |
| `commit` | `3f2a…` | The wire-builds commit; empty when unchanged. |

### Requirements

- `bash`, `jq`, `base64` and `gh` (all GitHub-hosted runners); no checkout.

### Behaviour

1. Checks every input before any call.
2. Reads the file and its blob sha. If the entry already has the version, the
   repo (when given) and every `meta` field given: `status=unchanged`, nothing
   is committed. A rerun after a commit that landed stops here.
3. Writes the new file: the entry's fields set, the other `meta` fields kept,
   the top-level version bumped. Normalized (`jq -S`), the file without
   `.version` and `.helmCharts.<chart>` must equal the one read: anything else
   fails the step before the commit.
4. `PUT /contents` with the blob sha read. A conflict (another commit landed)
   or a transient error: back to point 2, up to `attempts` times.

## Example

After the publication of the chart, in the publication job:

```yaml
      - uses: wireapp/wire-rm-actions/wire-builds-bump@<sha> # vX.Y.Z
        with:
          chart: my-component
          version: ${{ steps.manifest.outputs.version }}
          chart-repo: https://s3-eu-west-1.amazonaws.com/public.wire.com/charts
          commit: ${{ steps.manifest.outputs.source-commit }}
          token: ${{ secrets.WIRE_BUILDS_WRITE_ACCESS_GH_TOKEN }}
```

## Design notes

**The contents API, not a clone.** One read, one write, and the blob sha
makes the write a compare-and-swap: no `git push --force`, no rebase, no
window where a concurrent bump is lost. The commit is GitHub's, signed by it.

**A no-op first.** The question asked is "is the entry already there?", not
"did this run push?". So a rerun, a repair or a commit whose answer was lost
all end with `unchanged`, and the build version is never bumped twice for
the same chart version.

**Two fields, checked.** wire-builds feeds every deployment. A bug in this
step must not touch another chart: the normalized comparison refuses any
change outside `.version` and the chart's own entry.
