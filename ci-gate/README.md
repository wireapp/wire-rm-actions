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
**ci-gate** ·
[draft-release](../draft-release/README.md) ·
[publish-chart-s3](../publish-chart-s3/README.md)

# ci-gate

> Refuse a release preparation when the version is taken or the CI of its
> source commit did not pass.

## Definition

The first gates of a release preparation (ADR-0021 §1), before anything is
built:

| Gate | Fails when | Bypass |
|---|---|---|
| `release-gate` | a GitHub Release, draft or published, has the tag `<tag-prefix><version>`, or the tag exists | never |
| `checks-gate` | a required check of `source-commit` failed, is still running or never reported | `force: true`, logged as a warning and in the run summary |

Each check run is judged by its **latest** outcome on the commit, so a run
cancelled by a newer push and then rerun green passes. The runs of the
calling workflow (its own check runs sit on the commit it gates), of
`exclude-workflows` and of the GitHub-managed dynamic workflows (Dependabot)
are ignored.

| `checks-from` | Required checks | Passing |
|---|---|---|
| `all` | every check run of the commit, and the legacy statuses | not `failure`, `timed_out`, `cancelled`, `action_required`, nor running; at least one check run; combined status not `failure`, `error` or `pending` |
| `list` | the names in `required-checks` (check run name or status context) | `success`, `neutral` or `skipped`, like branch protection |
| `branch-rules` | the required status checks of the rulesets of `branch` | same as `list` |

An empty set of checks fails: "nothing ran" is never "everything passed".

## Technical reference

### Inputs

| Input | Default | Description |
|---|---|---|
| `version` | `""` | The version without the prefix; required by the release gate. |
| `tag-prefix` | `v` | Prefix of the git tag. |
| `source-commit` | `""` | Full sha of the commit; required by the checks gate. |
| `release-gate`, `checks-gate` | `true` | Run each gate. |
| `force` | `false` | Skip the checks gate, loudly. |
| `checks-from` | `all` | `all`, `list` or `branch-rules`. |
| `required-checks` | `""` | `list`: one name per line. |
| `branch` | `""` | `branch-rules`: the branch whose rulesets are read. |
| `exclude-workflows` | `""` | Workflow files ignored, one per line, on top of the calling one. |
| `exclude-dynamic` | `true` | Ignore the dynamic workflows (`dynamic/...`). |
| `repository` | `github.repository` | owner/name. |
| `token` | `github.token` | Token for `gh` (`GH_TOKEN`). |

### Outputs

| Output | Description |
|---|---|
| `tag` | The tag checked by the release gate. |
| `bypassed` | `true` when `force` skipped the checks gate. |
| `checks-inspected` | Check runs (`all`) or required checks (`list`, `branch-rules`) verified. |
| `status-state` | Combined state of the legacy statuses, `none` without any. |

### Requirements

- `bash`, `jq` and `gh` (all GitHub-hosted runners); no checkout.
- Token permissions: `contents: read` (releases, tags, branch rules),
  `checks: read`, `statuses: read`, `actions: read` (the workflow of each
  run, to exclude its own and the dynamic ones).

## Example

```yaml
    permissions:
      contents: write   # the draft release, later in the job
      checks: read
      statuses: read
      actions: read
    steps:
      - uses: wireapp/wire-rm-actions/ci-gate@<sha> # vX.Y.Z
        with:
          version: ${{ steps.version.outputs.version }}
          source-commit: ${{ steps.source.outputs.sha }}
          force: ${{ inputs.force }}
```

Only the required checks of the release branch:

```yaml
      - uses: wireapp/wire-rm-actions/ci-gate@<sha> # vX.Y.Z
        with:
          version: ${{ steps.version.outputs.version }}
          source-commit: ${{ steps.source.outputs.sha }}
          checks-from: branch-rules
          branch: ${{ inputs.source_branch }}
```

## Design notes

**The latest outcome, not the history.** A superseded run leaves `cancelled`
check runs on the commit next to the successful ones; the API's
`filter=latest` does not drop them. Grouping by name and keeping the latest
start also lets a rerun clear a failure, and still blocks a success followed
by a failure.

**Its own runs never count.** A failed preparation leaves its check run on
the commit forever: without the exclusion, the first failure would block every
retry. Excluded by workflow file, resolved from each run, so the dynamic
workflows are covered by path too, not by a job name a repository could reuse.

**The legacy statuses only when there are some.** The combined status of a
commit without any status is `pending`; judging it would fail every
repository that reports through check runs only.

**`force` is loud, and only for the checks.** A bypass is a warning
annotation and a summary section, never a silent pass; an existing release is
never bypassed.
