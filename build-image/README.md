[wire-rm-actions](../README.md) ·
[version](../version/README.md) ·
**build-image** ·
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
[publish-chart-s3](../publish-chart-s3/README.md)

# build-image

> Build a container image from a Dockerfile and push it at the build version,
> with its provenance and SBOM attestations, never overwriting a tag that is
> already in the registry.

## Definition

`build-image` builds the Dockerfile you give it with BuildKit, tags the image
with the build version (or the tag you pass, e.g. a release candidate tag),
stamps the OCI provenance labels and annotations (ADR-0020 rule 8), attaches
the SLSA provenance and SBOM attestations and pushes it all. It outputs the
digest read back from the registry, ready for the release manifest and for a
later promotion by digest ([promote-image](../promote-image/README.md)). The
component only describes **what** to build: the Dockerfile, its context and
its build inputs.

## Technical reference

### Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `dockerfile` | yes | | Path of the Dockerfile. A `<Dockerfile>.dockerignore` next to it wins over `<context>/.dockerignore`. |
| `image` | yes | | Image repository, e.g. `quay.io/wire/my-component`. The registry host is its first segment. |
| `version` | yes | | The version, from [version](../version/README.md): the `org.opencontainers.image.version` label and the default tag. |
| `tag` | no | the version | Tag to push. A release candidate passes `<version>-candidate-<run id>`. |
| `context` | no | `.` | Build context directory. |
| `build-args` | no | `""` | `KEY=VALUE` lines passed as `--build-arg`. Never secrets: they stay in the image history. |
| `build-contexts` | no | `""` | `name=path` lines passed as `--build-context`: files the Dockerfile reads from outside the context (`COPY --from=<name>`). |
| `target` | no | the last stage | Dockerfile stage to build. |
| `platforms` | no | `linux/amd64` | Comma-separated platforms. More than one sets up QEMU and pushes a multi-platform index. |
| `revision` | no | the run commit | Source commit, for the `org.opencontainers.image.revision` label. |
| `labels` | no | `""` | More OCI labels as `KEY=VALUE` lines (e.g. `org.opencontainers.image.title`, `.description`, `.url`), set as label and as annotation like the stamped ones. Not `version`, `revision`, `source`, `created` nor `quay.expires-after`: the action sets those. |
| `provenance` | no | `mode=max` | SLSA provenance attestation pushed with the image: `mode=max`, `mode=min`, `true` (= `mode=min`) or `false`. |
| `sbom` | no | `true` | SBOM attestation pushed with the image: `true` or `false`. |
| `expires-after` | no | `""` | Dev builds only: Quay deletes the image after this delay (`90d`, or hours `h`, days `d`, weeks `w`). Empty keeps it. |
| `username` | no | `""` | Registry user (a Quay robot account of the team). Empty: the job is already logged in, e.g. by [quay-login](../quay-login/README.md). |
| `password` | no | `""` | Registry password or token, with `username`. |

### Outputs

| Output | Example | Description |
|---|---|---|
| `image` | `quay.io/wire/my-component` | The image repository. |
| `tag` | `1.41.5-20261013120000.gabcdef0` | The tag pushed, or already present. |
| `digest` | `sha256:4f1c…` | Digest of the image index, read from the registry. |
| `ref` | `quay.io/wire/my-component@sha256:4f1c…` | The immutable reference. |
| `status` | `pushed` | `pushed`, or `present` when the tag was already in the registry. |

### Requirements

- A Docker engine on the runner (GitHub-hosted Ubuntu runners have one); the
  action sets up Buildx itself, and QEMU for a multi-platform build.
- A registry login with write access to the image repository: either
  `username` and `password` (a robot account), or a step before this one
  that logged in, such as [quay-login](../quay-login/README.md).
- Whatever the Dockerfile copies must be in the context (or a named
  `build-contexts` entry) **before** this step: download build artifacts
  first, the action builds what it is given.

### Behaviour

1. With `username`: logs in to the registry of `image`, the password on
   stdin. Without: uses the login of the job.
2. If `<image>:<tag>` is already in the registry: nothing is built, the
   existing digest is read back (`status=present`).
3. Otherwise: `docker buildx build --push` with the Dockerfile, context, build
   arguments, named contexts and target, the labels and annotations
   `org.opencontainers.image.version`, `.revision`, `.source` and `.created`
   (the build time, UTC) and those of `labels`, the
   `provenance` and `sbom` attestations, and with `expires-after` the
   `quay.expires-after` label.
4. Reads the digest back from the registry and checks it is the one the build
   pushed.
5. With `username`: logs out of the registry, also when a previous step
   failed.

Malformed inputs fail before any build.

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
  dev-build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 0
          persist-credentials: false
      - id: version
        uses: wireapp/wire-rm-actions/version@<sha> # vX.Y.Z
      - uses: wireapp/wire-rm-actions/quay-login@<sha> # vX.Y.Z
        with:
          robot: wire+gha_my-component
      - id: image
        uses: wireapp/wire-rm-actions/build-image@<sha> # vX.Y.Z
        with:
          dockerfile: docker/Dockerfile
          image: quay.io/wire/my-component
          version: ${{ steps.version.outputs.version }}
          platforms: linux/amd64,linux/arm64
          build-args: |
            REVISION=${{ steps.version.outputs.version }}
          expires-after: 90d
      # Then publish-chart: the chart defaults its image tag to the version.
```

Without a federated robot, pass `username: ${{ secrets.QUAY_USER }}` and
`password: ${{ secrets.QUAY_TOKEN }}` instead of the `quay-login` step.

A release candidate passes `tag: <version>-candidate-${{ github.run_id }}`
and no `expires-after`; publication promotes `steps.image.outputs.digest` to
the release tag with [promote-image](../promote-image/README.md), without
rebuilding.

## Design notes

**One build per tag.** A tag already in the registry is never rebuilt nor
overwritten: a rerun of the same commit reads the digest back. The digest that
the release manifest records is the one that ships.

**The component says what, the action says how.** Login, Buildx, platforms,
provenance labels, attestations, immutability and logout are the same for
every component; only the Dockerfile and its inputs differ.

**Attestations ride with the image.** The SLSA provenance and the SBOM are
pushed as extra manifests of the image index, under the same tag: the
promotion by digest carries them to the release tag, and a scanner finds them
next to the image. `mode=max` records the full build inputs; a Dockerfile that
must not disclose them passes `mode=min`. Both can be turned off, for a
registry that cannot hold an index.

**The digest comes from the registry.** The local builder is not
authoritative: the action reads the digest back and fails when it differs
from the one the build reported.

**No secrets in build arguments.** Build arguments are recorded in the image
history: credentials a build needs belong in a BuildKit secret, not here.

**Credentials stay short-lived.** The password reaches Docker on stdin, and
the action logs out when done, so the later steps of the job never find it in
`~/.docker/config.json`. With [quay-login](../quay-login/README.md) there is
no password at all.
