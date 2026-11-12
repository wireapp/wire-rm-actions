[wire-rm-actions](../README.md)

# Workflow templates

Workflows a component copies into its own `.github/workflows/`, then adapts:
component id, robot account, chart repositories, and the commit SHA of a
release on every `wireapp/wire-rm-actions` action
([Pin a release](../README.md#pin-a-release)). In this repository they call
the actions at `@dev`; `make release-prep` points them at the release.

| Template | What it does |
|---|---|
| [`repair-publication.yml`](repair-publication.yml) | Replays what comes after the tag for a published release (declaration to the release managers, S3 chart, wire-builds bump), from the assets of the GitHub Release, without any build. |

## When to repair, when to rerun

A publication that fails **before** the tag is rerun as is: every step up to
the publication of the draft is idempotent.

A publication that fails **after** the tag can be rerun as well:
[draft-release](../draft-release/README.md) resumes on a published release
(same commit, same manifest) and changes nothing on it, so the later steps
run again. `repair-publication.yml` is for the other cases: the original run
is too old to rerun, one step must be replayed on its own, or the declaration
must go out again after a fix in the release manager. It needs a typed
confirmation (`v<version>`), a reason, and the approval of the
`release-publication` environment.

## One publication at a time

The publish-release workflow of a component and the repair share one
concurrency group per repository, never cancelled:

```yaml
concurrency:
  group: publish-${{ github.repository }}
  cancel-in-progress: false
```

A group per version (`publish-release-${{ inputs.version }}`) lets two
versions publish at once: both decide `make_latest`, both bump wire-builds.
One group per repository queues them instead.
