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
**draft-release** ·
[publish-chart-s3](../publish-chart-s3/README.md)

# draft-release

> Create the draft GitHub Release of a candidate, find it again at
> publication, and publish it last.

## Definition

A release candidate lives as a **draft** GitHub Release (ADR-0021 §3, §4):
its body and every artifact (chart package, release manifest, release note,
release declaration) are attached at preparation, reviewed while the
publication waits for approval, and the draft is published last, which
creates the tag on the commit it targets.

| Mode | When | What |
|---|---|---|
| `create` | prepare | Refuses an existing release for the tag, creates the draft on `target` with `title`, `body-file` and `assets`, and returns its id. |
| `resolve` | publish, first | Finds the draft (`release-id`, else the only draft with the tag), checks it, checks the tag state, downloads its assets into `asset-dir`. |
| `publish` | publish, last | The same checks, replaces `replace-assets`, decides `make_latest`, publishes the draft. |

The checks of `resolve` and `publish`: the release is a draft, has the tag
`<tag-prefix><version>` and targets `expected-commit` when given; the tag is
absent, or already at the target commit (a publication completed earlier),
never at another commit. The sha256 of the downloaded assets is checked by
[release-manifest](../release-manifest/README.md) `verify`, not here.

`make-latest: auto` is `true` for a GA whose `source-ref` matches
`latest-branches`, unless a newer GA tag already exists (it went out while
the approval waited); `false` otherwise.

## Technical reference

### Inputs

| Input | Modes | Description |
|---|---|---|
| `mode` | all | `create`, `resolve` or `publish`. |
| `version`, `tag-prefix` | all | The version, without the prefix (default `v`). |
| `target` | create | Full sha of the commit the tag will point to. |
| `title` | create | Default the tag. |
| `body-file` | create | The release body (markdown), written by the caller; empty for none. |
| `prerelease` | create | `auto` (the version has a `-` suffix), `true` or `false`. |
| `assets` | create, resolve | create: files to attach, one per line; resolve: more asset names to download. |
| `release-id`, `expected-commit` | resolve, publish | The draft id (empty: found by tag) and the commit it must target. |
| `asset-dir` | resolve | Default `$RUNNER_TEMP/release-assets`. |
| `download` | resolve | `none`, `manifest` (default), `manifest-files` (the manifest and every `file` of its `artifacts` and `documents`) or `all`. |
| `manifest-name` | resolve | Default `release-manifest.json`. |
| `replace-assets` | publish | One per line, `<path>` or `<name>=<path>`: deleted and uploaded again before publication. |
| `make-latest` | publish | `auto` (default), `true`, `false` or `legacy`. |
| `source-ref`, `latest-branches` | publish | The candidate's branch and the regex of the branches whose GA is Latest (default `^dev$`). |
| `repository`, `token` | all | Default `github.repository` and `github.token`. |

### Outputs

| Output | Modes | Description |
|---|---|---|
| `id`, `tag`, `url` | all | The release; `url` is the draft URL, the published one after `publish`. |
| `published-url` | create | The URL once published (404 until then). |
| `target-commitish`, `prerelease`, `tag-exists` | resolve | The draft's commit, kind, tag state. |
| `asset-dir`, `manifest`, `body-file` | resolve | Where the assets are, the manifest path (empty when not downloaded), the body. |
| `make-latest` | publish | The value sent. |

### Requirements

- `bash`, `jq` and `gh` (all GitHub-hosted runners); no checkout.
- Token permissions: `contents: write` in every mode. `resolve` only reads,
  but GitHub lists draft releases to push access only.

## Example

Prepare, after the [ci-gate](../ci-gate/README.md) and the
[release-manifest](../release-manifest/README.md) `write`:

```yaml
      - id: release
        uses: wireapp/wire-rm-actions/draft-release@<sha> # vX.Y.Z
        with:
          mode: create
          version: ${{ steps.version.outputs.version }}
          target: ${{ steps.source.outputs.sha }}
          body-file: ${{ runner.temp }}/release-body.md
          assets: |
            ${{ runner.temp }}/release/my-component-${{ steps.version.outputs.version }}.tgz
            ${{ runner.temp }}/release/release-manifest.json
            ${{ steps.documents.outputs.note-file && format('{0}/release/{1}', runner.temp, steps.documents.outputs.note-file) }}
```

Publish, in the job gated by the `release-publication` environment:

```yaml
      - id: draft
        uses: wireapp/wire-rm-actions/draft-release@<sha> # vX.Y.Z
        with:
          mode: resolve
          version: ${{ inputs.version }}
          release-id: ${{ inputs.release_id }}
          download: manifest-files
      - id: manifest
        uses: wireapp/wire-rm-actions/release-manifest@<sha> # vX.Y.Z
        with:
          mode: verify
          manifest: ${{ steps.draft.outputs.manifest }}
          asset-dir: ${{ steps.draft.outputs.asset-dir }}
          version: ${{ inputs.version }}
          source-commit: ${{ steps.draft.outputs.target-commitish }}
      # Promote the artifacts, then complete the manifest.
      - uses: wireapp/wire-rm-actions/draft-release@<sha> # vX.Y.Z
        with:
          mode: publish
          version: ${{ inputs.version }}
          release-id: ${{ steps.draft.outputs.id }}
          expected-commit: ${{ steps.manifest.outputs.source-commit }}
          source-ref: ${{ steps.manifest.outputs.source-ref }}
          replace-assets: release-manifest.json=${{ steps.completed.outputs.manifest }}
```

## Design notes

**One action, three modes.** Creation and publication share what is hard:
finding a draft (absent from `/releases/tags/{tag}`, several drafts may
share a tag) and judging the tag state. One script keeps a single definition,
like `release-manifest` `write`/`verify`/`complete`.

**The body is the caller's.** What a release says is the component's: the
caller writes the body file, the action only attaches it. It is written once
and never rewritten, so it must read correctly after publication.

**Drafts by id, after a retried lookup.** The releases list is eventually
consistent: right after `gh release create` the draft can be missing for a
few seconds. The lookup is retried; more than one match is a conflict, never
a guess.

**Published last, and only once.** `publish` is the last write: the tag is
born there, on the commit the draft targets. A release that is no longer a
draft is refused, and a tag at another commit stops the publication before
anything changes.
