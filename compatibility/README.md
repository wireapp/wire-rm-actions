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
**compatibility** ·
[release-inputs](../release-inputs/README.md) ·
[release-source](../release-source/README.md) ·
[promote-image](../promote-image/README.md) ·
[ci-gate](../ci-gate/README.md) ·
[draft-release](../draft-release/README.md) ·
[publish-chart-s3](../publish-chart-s3/README.md)

# compatibility

> Check what a component provides, consumes, depends on and includes, and hand
> it to the release manifest in the shape the release manager reads.

## Definition

`publication/compatibility.yaml` (ADR-0020 §3) says which interfaces a
component serves (`providesApis`), which it needs from others
(`consumesApis`), which foundation, platform or component versions it depends
on (`dependsOn`) and which components it ships inside itself (`includes`).
`compatibility` checks the file and writes it as JSON twice:

| Output file | Shape | For |
|---|---|---|
| `compatibility` | the ADR-0020 document as is | the manifest once the release manager reads the ADR-0020 names |
| `manifest-compatibility` | `provides`, `requires`, `includes` | the `compatibility` field of a `wire.component-release-manifest/v1alpha1` manifest, what the release manager reads today |

```yaml
providesApis:
  - api: wire-server/client-api
    versions:
      supported: [4, 5, 6]
      deprecated: [4]
      development: [7]
  - api: wire-server/scim-api
    versions: ["2.0.0"]
consumesApis:
  - api: wire-server/admin-api
    versions: "^0"
    reason: Informational, version 0.
dependsOn:
  - resource: postgresql
    range: ">=17.0.0"
    class: mandatory
  - platform: kubernetes
    range: ">=1.29.0"
includes: []
```

## Technical reference

### Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `file` | no | `""` | Path of the compatibility file; empty reads `publication/compatibility.yaml`. |
| `output-dir` | no | `""` | Directory for the JSON files; empty uses a new temporary directory. |

### Outputs

| Output | Description |
|---|---|
| `file` | The compatibility file that was read. |
| `compatibility` | Path of the ADR-0020 document as JSON. |
| `manifest-compatibility` | Path of the `provides` / `requires` / `includes` object. |

### Requirements

- `bash`, `jq` and [mikefarah's `yq`](https://github.com/mikefarah/yq) v4
  (all GitHub-hosted Ubuntu runners). `make tools` pins `yq` for the tests.

### Behaviour

- The four ADR-0020 lists are required (`[]` when empty) and no other key is
  allowed. A file that mixes them with `provides` or `requires` fails.
- `providesApis[].versions` is `{supported, deprecated, development}` with
  integer API versions, or a list of SemVer versions for other interfaces.
  `consumesApis[].versions` is a list of API versions or a range.
- `dependsOn` entries name exactly one of `resource`, `component` or
  `platform`, with a `range`. `class` is `mandatory`, `optional` or
  `alternative`; an `optional` or `alternative` entry needs a `reason`.
- `includes` entries have a `component`, one of `version` or `range`, a
  `reason`, and no `class`: an inclusion is unconditional.
- Interface ids are not checked against the registry here.
- Every error is reported, one `::error::` line each; nothing is written then.
- Mapping to the manifest shape: `api` becomes `interface`, `resource` becomes
  `capability`, `versions` becomes `range`; a contiguous list of API versions
  becomes `"<min>-<max>"`, another list its versions joined with `,`;
  `alternative` becomes `optional`. The output matches the former per-component
  `bin/compatibility-manifest.sh` scripts on their fixtures.

## Example

Replace `<sha>` with the commit of a release tag ([Pin a release](../README.md#pin-a-release)).

```yaml
      - id: compatibility
        uses: wireapp/wire-rm-actions/compatibility@<sha> # vX.Y.Z
      - name: Write the release manifest
        env:
          COMPATIBILITY: ${{ steps.compatibility.outputs.manifest-compatibility }}
        run: |
          jq -n --slurpfile compatibility "$COMPATIBILITY" '{
            schemaVersion: "wire.component-release-manifest/v1alpha1",
            compatibility: $compatibility[0]
          }' >release-manifest.json
```

Then send the manifest with [notify-rm](../notify-rm/README.md)
(`release-manifest-file`).

## Design notes

**One reading of the file for every component.** Components each
had their own script to read the file; a format change meant two changes, one
of them forgotten. The check and the mapping live here once.

**Both shapes until the release manager moves.** The release manager still
refuses the ADR-0020 names. Writing both lets components move their file to
`publication/` now, without waiting for it; the `manifest-compatibility`
output goes away once it reads the new names.
