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
**promote-image** ·
[ci-gate](../ci-gate/README.md) ·
[draft-release](../draft-release/README.md) ·
[publish-chart-s3](../publish-chart-s3/README.md)

# promote-image

> Give the candidate image of a release its release tag, by digest, without
> any rebuild. Already there with the same digest: nothing to do. Already there
> with another digest: refused.

## Definition

A release publishes the exact image that was prepared and approved (ADR-0020
rule 3). `promote-image` reads the candidate by digest from the release
manifest, checks it still exists, and writes the release tag against that
manifest with `crane tag`: a multi-arch index keeps its digest, nothing is
pulled or pushed again. It outputs the digest the release tag resolves to and
whether it did anything.

## Technical reference

### Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `repository` | yes | | Image repository, e.g. `quay.io/wire/my-component`. |
| `digest` | yes | | `sha256:…` digest of the candidate, from the release manifest. |
| `tag` | yes | | Release tag to write, `X.Y.Z` or `X.Y.Z-<alpha\|beta\|rc>.N`. |
| `username` | no | `""` | Registry user; empty when the job is already logged in ([quay-login](../quay-login/README.md)). |
| `password` | no | `""` | Registry password or token, with `username`. |
| `crane-version` | no | `v0.22.1` | Release of `crane` installed for this job when none is on `PATH`; change `crane-sha256` with it. |
| `crane-sha256` | no | the Linux x86_64 archive of `v0.22.1` | sha256 of the `go-containerregistry_<OS>_<arch>.tar.gz` archive of that release for the runner: another version or architecture (an arm64 runner) needs its own, from the release's `checksums.txt`. |

### Outputs

| Output | Example | Description |
|---|---|---|
| `digest` | `sha256:4f1c…` | What the release tag resolves to (always the input digest). |
| `status` | `promoted` | `promoted`, or `present` when the tag was already at that digest. |

### Requirements

- `crane` on `PATH`, or `curl` and `tar` on the runner: the release archive is
  downloaded, checked against `crane-sha256` and unpacked for this job only.
- Write access to the repository: a login done before (`docker login`,
  [quay-login](../quay-login/README.md)) or `username` and `password`.

### Behaviour

1. Checks every input before touching the registry; logs in on stdin when a
   user is given.
2. `crane manifest <repository>@<digest>`: a candidate that disappeared fails
   the step (prepare the release again, never rebuild at publication).
3. Resolves the release tag **before** writing it (`crane tag` overwrites
   silently): same digest, `status=present`; another digest, failure.
4. `crane tag`, then resolves the tag again and compares it to the digest.
5. Logs out when this action logged in, also on failure.

## Example

```yaml
      - id: image
        uses: wireapp/wire-rm-actions/promote-image@<sha> # vX.Y.Z
        with:
          repository: ${{ steps.manifest.outputs.image-repository }}
          digest: ${{ steps.manifest.outputs.image-digest }}
          tag: ${{ steps.manifest.outputs.version }}
```

after [quay-login](../quay-login/README.md) in the same job, or with
`username` and `password` from a robot account.

## Design notes

**Publication never builds.** What was tested is what ships: the tag is a
pointer to the approved manifest. A rebuild, even from the same commit, would
be another artifact with another digest.

**A pinned binary, not a build.** `crane` comes from the release archive of
`crane-version`, checked against `crane-sha256` before it is unpacked
(`scripts/install-crane.sh`): the same bytes on every run, no Go toolchain, no
module proxy and no checksum database in the trust chain of a publication. A
runner that already has `crane` keeps its own.

**Idempotent, never destructive.** A rerun after a failure later in the job
finds the tag at the right digest and continues. A tag at another digest means
someone published something else under this version: the step stops, nobody
overwrites it by accident.
