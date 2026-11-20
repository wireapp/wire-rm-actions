# Releasing a component

What the actions of this repository expect from a component, and how this
repository applies it to itself. A component is anything the release managers
track: a service with an image and a chart, a chart that repackages an
upstream release, or, as here, a set of GitHub Actions with no artifact at
all. The contract is the same; the artifact steps are the part that varies.

## One version

- A version is SemVer, `X.Y.Z`, tagged `vX.Y.Z` on the commit it was built
  from. A pre-release is `X.Y.Z-alpha.N`, `-beta.N` or `-rc.N`, `N` from 1,
  and sorts below its GA. Tags of another form are not releases.
- The application, its image and its chart carry **one** version: the image
  tag is the version, the chart `version` equals its `appVersion` and both
  equal the version ([publish-chart](../publish-chart/README.md) sets them,
  whatever `Chart.yaml` says). A chart that repackages an upstream release is
  the one exception: its `appVersion` stays the upstream version.
- A dev build is `X.Y.(Z+1)-<timestamp>.g<sha7>` after a GA, or
  `X.Y.Z-rc.N.<timestamp>.g<sha7>` after a pre-release; outside the trunk and
  the release lines it also carries the branch
  ([version](../version/README.md)). Dev builds expire; releases do not.
- A published version is never overwritten: not a tag, not an image tag, not
  a chart version, not a release. A rerun finds what is there and goes on.
- The trunk is `dev`, the default branch. A maintained line is
  `release/X.Y`, created at its first GA. A fix lands on the trunk first and
  is backported.

## The publication folder

Three files at the root of the repository, in `publication/`, rewritten for
every release and reviewed in pull requests like the code they describe:

| File | What it says | Who reads it |
|---|---|---|
| `compatibility.yaml` | What the component serves (`providesApis`), needs from others (`consumesApis`), depends on (`dependsOn`: resources, platforms, components) and ships inside itself (`includes`). | [compatibility](../compatibility/README.md), then [release-manifest](../release-manifest/README.md): the release manager derives the requirements of a version from it. |
| `release-note.md` | What a reader learns about the next version: what changes, what to do before upgrading. Markdown, no fixed shape. | [release-documents](../release-documents/README.md): attached to the GitHub Release and shown in its body; dev builds point at it and warn when it is missing. |
| `declaration.json` | What an operator must know before upgrading to the next GA: changes, migrations, configuration keys, and on `X.Y.0` the support dates. Schema `wire.component-release/v1alpha2`, `version` is the GA its pre-releases share. | [release-declaration](../release-declaration/README.md) validates it; [notify-rm](../notify-rm/README.md) sends it with the version. |

Rules the actions enforce:

- The four lists of `compatibility.yaml` are present, `[]` when empty, and
  nothing else is. `providesApis` and `consumesApis` list only interfaces that
  are versioned by code and present in the interface registry; a protocol or
  a link with no negotiated version is `dependsOn` with
  `component: <name>` and `range: "*"`.
- Every section of `declaration.json` but `support` is present: `[]` is an
  explicit "nothing to declare", a missing section is an error. The file is
  valid for the component id and for the GA version of the release being
  prepared, and formatted (`jq --indent 2`).
- A GA cannot start without the note and the declaration; a pre-release
  warns. The components require all three files for a pre-release as well:
  the files are written when the work is done, not on release day.
- The release manager can send a note and a declaration with its request
  (`release_note`, `release_declaration` dispatch inputs); the repository
  file wins for the note unless the workflow says otherwise.

Examples: [`testdata/compatibility/ok-my-component.yaml`](../testdata/compatibility/ok-my-component.yaml),
[`testdata/release-declaration/valid-v1alpha2.json`](../testdata/release-declaration/valid-v1alpha2.json),
and this repository's own [`publication/`](../publication/).

## Artifacts

| Component ships | Dev build | Release |
|---|---|---|
| image and chart | [build-image](../build-image/README.md) at the version with provenance and SBOM (an expiring image without them), then [publish-chart](../publish-chart/README.md) to `oci://quay.io/wire/charts/dev/<name>` | [promote-image](../promote-image/README.md) tags the dev build's digest with the release tag, [publish-chart](../publish-chart/README.md) pushes the packaged chart of the draft to the `stable` channel for a GA |
| chart only | the same without the image (`chart-only: true` in the manifest) | the same without the image |
| other files (a bundle, an archive) | `extra-artifacts-json` of the manifest, attached to the release | verified by sha256 against the manifest |
| nothing (this repository) | no dev build | the tagged commit and the GitHub Release |

The image goes before the chart: a chart must never point at a missing image.
The registry is `quay.io`, the robot `wire+gha_<repository>`, logged in with
the OIDC token of the job ([quay-login](../quay-login/README.md)).

## The manifest and the release managers

Every build with an artifact writes a release manifest
([release-manifest](../release-manifest/README.md)): the source commit, the
artifacts by digest, the `compatibility` block, the documents and the run. At
publication the manifest is verified against the downloaded assets, completed
with the published digests, and declared with the version to the staging and
production release managers by [notify-rm](../notify-rm/README.md), together
with the release declaration and the release URL. The component id sent is
the id the release manager knows; the repository is bound there to the
components it may declare (`oidc.repositories`: name, id, components), and
the job's OIDC token is the only credential.

## Workflows

**Dev build**, on every push to the trunk and the release lines
([Quick start](../README.md#quick-start), or the
[reusable workflow](../README.md#reusable-workflow) for a chart-only component):
version, image, chart, manifest, declaration to the release managers.

**Prepare release**, a `workflow_dispatch` on the trunk or a release line
with `source_branch`, `type` (`alpha`, `beta`, `rc`, `ga`), `bump` (`patch`,
`minor`, `major`) and `force`, plus the inputs a release manager request
adds (`request_id`, `rm_origin`, `expected_version`, `release_note`,
`release_declaration`):

1. [release-inputs](../release-inputs/README.md) checks the inputs before the
   checkout; [release-source](../release-source/README.md) verifies the branch,
   records the commit and writes the candidate's identity to the summary.
2. [version](../version/README.md) in release mode computes the version from the
   latest release reachable; [ci-gate](../ci-gate/README.md) refuses a version
   already released and a source commit whose checks did not pass.
3. The three publication files are required; [release-documents](../release-documents/README.md)
   validates the declaration and gathers the documents;
   [compatibility](../compatibility/README.md) checks the file.
4. The artifacts of the candidate are packaged or resolved (the dev build of
   the source commit), the manifest is written, the
   [changelog](../changelog/README.md) since the previous release is composed
   into the body.
5. [draft-release](../draft-release/README.md) creates the draft GitHub Release
   on the source commit, with the artifacts, the manifest and the documents
   as assets. Nothing is tagged yet.

**Publish release**, the job gated by the `release-publication` environment,
called by the preparation and dispatched by hand with the version as the
recovery path:

1. The draft is resolved and its assets downloaded; the manifest is verified
   against them, the version and the source commit, which must still be on
   its branch.
2. The artifacts are promoted, never rebuilt: the image by digest, the chart
   from the asset. The manifest is completed with the published digests.
3. The draft is published, which creates the tag; a first GA of a minor
   creates `release/X.Y`; [notify-rm](../notify-rm/README.md) declares the
   release. Every step is idempotent, so a failed publication is rerun.

## Repository settings

- Default branch `dev`; a pull request for every change; signed commits.
- Environment `release-publication`: required reviewers are the release
  managers; deployment branches `dev` and `release/*`.
- Tag ruleset on `v*`: no update, no deletion; releases immutable.
- Variables `RM_STAGING_URL` and `RM_PROD_URL` (a public repository reads
  them as secrets instead). Audiences `wire-release-manager-staging` and
  `wire-release-manager-prod`.
- The Quay robot `wire+gha_<repository>` with a federation entry for each
  branch and environment that publishes; the repository bound in the release
  managers to its components.
- Third-party actions pinned by commit SHA, with the version in a comment,
  and Dependabot on the `github-actions` ecosystem.

## This repository

wire-rm-actions is its own first component, with no artifact: a release is a
signed commit of `dev`, tagged, with a GitHub Release whose body carries the
release note, the changelog and the line consumers pin.

- [`publication/`](../publication/) holds the three files. The compatibility
  file is four empty lists: the actions run on GitHub-hosted runners and
  deploy nothing. The note and the declaration describe the next version;
  `make ci` validates them.
- [`prepare-release.yml`](../.github/workflows/prepare-release.yml) and
  [`publish-release.yml`](../.github/workflows/publish-release.yml) are the two
  workflows above without the artifact steps, calling the actions of the
  source commit at `./<action>`: a release of the actions cannot pin itself.
  The preparation also requires that the reusable workflow calls the actions
  at the tag being released (`make release-prep VERSION=vX.Y.Z`,
  [`scripts/check-release-ref.sh`](../scripts/check-release-ref.sh)), so a
  consumer who pins the release gets a reusable workflow that calls the same
  release.
- The publication checks the draft's assets against the publication files of
  the source commit byte for byte, requires the commit to be on `dev` or a
  `release/X.Y` branch, and publishes the draft: the tag is born there, after
  the approval of a release manager.
- No manifest and no declaration to the release managers: there is nothing to
  deploy. No `release/X.Y` line either, until a release has to be maintained.

The release procedure itself is in [CONTRIBUTING.md](../CONTRIBUTING.md#release).
