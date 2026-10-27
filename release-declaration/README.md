[wire-rm-actions](../README.md) ·
[version](../version/README.md) ·
[build-image](../build-image/README.md) ·
[quay-login](../quay-login/README.md) ·
[publish-chart](../publish-chart/README.md) ·
[notify-rm](../notify-rm/README.md) ·
[changelog](../changelog/README.md) ·
**release-declaration** ·
[release-documents](../release-documents/README.md) ·
[release-manifest](../release-manifest/README.md) ·
[compatibility](../compatibility/README.md) ·
[release-inputs](../release-inputs/README.md) ·
[release-source](../release-source/README.md) ·
[promote-image](../promote-image/README.md) ·
[ci-gate](../ci-gate/README.md) ·
[draft-release](../draft-release/README.md) ·
[publish-chart-s3](../publish-chart-s3/README.md)

# release-declaration

> Validate a release declaration, what a version changes for an operator,
> against the schema of this repository, before it is published.

## Definition

A release declaration (ADR-0020 §4, `wire.component-release/v1alpha2`,
`publication/declaration.json`) is a JSON document a component writes for each
GA, shared by its pre-releases: what changes, what breaks, which migrations
run and which configuration keys change. `release-declaration` checks it
against
[`schemas/wire.component-release-v1alpha2.json`](../schemas/wire.component-release-v1alpha2.json)
and fails on any error; [notify-rm](../notify-rm/README.md) then sends it to
the release manager with the version.

| Section | Each entry holds |
|---|---|
| `changes` | `kind` (`added`/`changed`/`deprecated`/`removed`/`fixed`/`security`), `description`, `breaking`, `links` |
| `migrations` | `kind` (`schema`/`data`/`manual`), `automatic`, `description`, `downtime`, `reversible`; optional `order` |
| `configuration` | `key`, `change`, `required`, `description`; optional `default` |
| `support` | optional, on `X.Y.0`: `releaseCycle`, `releaseDate`, `lts`, `eoas`, `eol` |

Every section but `support` is required: an empty list is an explicit
"nothing to declare". `version` is the GA (`X.Y.Z`).

```json
{
  "schemaVersion": "wire.component-release/v1alpha2",
  "component": "my-component",
  "version": "4.25.0",
  "summary": "Maintenance release, nothing to do before deploying.",
  "upgrade_from": ">=4.24.0",
  "changes": [],
  "migrations": [],
  "configuration": []
}
```

Complete examples: [`testdata/release-declaration/valid.json`](../testdata/release-declaration/valid.json)
and [`valid-v1alpha2.json`](../testdata/release-declaration/valid-v1alpha2.json).

## Technical reference

### Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `file` | yes | | Path of the release declaration (JSON). |
| `component` | no | `""` | Component id the document must declare; empty skips the check. |
| `version` | no | `""` | Version the document must declare; empty skips the check. |

No outputs: the step passes or fails.

### Requirements

- `bash` and `jq` (all GitHub-hosted runners). No Python, no package.

### Behaviour

- A missing file, or a file that is not JSON, fails at once.
- Otherwise every error is reported, one `::error::` line each, with its JSON
  path: `$.features[0].default: must be one of ["on","off"]`.
- `component` and `version`, when given, must equal the document's fields.
- The schema keywords checked are `type`, `const`, `enum`, `required`,
  `properties`, `additionalProperties`, `items`, `pattern`, `minLength` and
  `maxLength`: the schema uses no other.
- Values taken from the document are escaped in the messages, so a document
  cannot inject a workflow command into the log.

## Example

Replace `<sha>` with the commit of a release tag ([Pin a release](../README.md#pin-a-release)).

```yaml
name: Release declaration

on:
  pull_request:
    paths: [release-declaration.json]

permissions: {}

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  validate:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: wireapp/wire-rm-actions/release-declaration@<sha> # vX.Y.Z
        with:
          file: release-declaration.json
          component: my-component
```

In the release workflow, validate it again with the released `version`, then
pass it to [notify-rm](../notify-rm/README.md) as `release-declaration-file`.

## Design notes

**Operators read declarations, not diffs.** Whoever upgrades Wire needs to
know what breaks, what to migrate and what to configure, not which commits
landed. The declaration says it in a fixed shape the release manager can
aggregate across components.

**Silence is not an answer.** Every section is mandatory: "no breaking change"
is written as `[]`, on purpose, by someone who checked. A forgotten section is
an error, not an empty one.

**One schema, one source of truth.** The schema is vendored here and read as
is: the action interprets it with jq, so there is no second copy of the rules
to drift. The tests check that jq and a real JSON Schema validator agree on
every fixture.

**Every error at once.** A failed check lists all the problems of the document,
so a release is fixed in one round trip, not one error per CI run.
