# wire-rm-actions 0.2.0

The second release of the shared actions, from the first weeks of use by the
components. The inputs are unchanged and a workflow pinned at 0.1.0 keeps
working when it moves to 0.2.0, with one exception in build-image (see
Upgrade). You also get clearer messages, a few fixes and a new action for
extra charts.

## What changes

- **notify-rm** tells a refused credential (HTTP 401) from a refused
  declaration (HTTP 403) and quotes the reason the release manager gives, as a
  titled annotation on the run. A 401 with a reason is a policy refusal of a
  bound repository, not a missing binding.
- **changelog** reads `feat!:` and `feat(scope)!:` as breaking changes.
- **build-image** builds an image that expires without provenance and SBOM
  attestations: Quay never expires an index whose attestation manifests carry
  no expiry, so dev images never expired. Asking for both an expiry and the
  attestations now fails before the build.
- **publish-chart** creates the destination of `helm pull`, so the presence
  check works again, and stops when that check fails for another reason than
  an absent version: a network error or a 5xx no longer pushes over a
  published version. It builds the dependencies of an `apiVersion: v1` chart
  (`requirements.yaml`) and skips the build when they are all in `charts/`.
- **publish-extra-chart**, new: pushes a chart that repackages an upstream
  release, with its own `appVersion`, where publish-chart keeps `appVersion`
  equal to the version. **notify-rm** takes the same value as `app-version`,
  so the release manager records the upstream release.
- **release-manifest** writes the manifest of a chart-only component
  (`chart-only: true`), such as a chart that repackages an upstream release.
- **version** reads an anchor tag `vX.Y.Z-0`: it names the next release of a
  branch where no release tag leads to it. Dev builds are `X.Y.Z-<ts>.g<sha7>`
  until then, and release mode gives `X.Y.Z` or `X.Y.Z-<channel>.1`. When a GA
  and a pre-release of a later version sit on the same commit, a dev build now
  starts from the pre-release, as release mode does.
- This repository releases itself the way it asks components to: the three
  publication files, a prepare-release and a publish-release workflow, and
  [docs/releasing.md](https://github.com/wireapp/wire-rm-actions/blob/dev/docs/releasing.md) as the written contract.

## Upgrade

Replace the pinned commit of `v0.1.0` with the one of `v0.2.0` in every
`uses: wireapp/wire-rm-actions/...` line and in the reusable workflow
reference. Dependabot proposes it.

A workflow that passes `expires-after` to build-image together with an
explicit `provenance` or `sbom` now fails before the build: drop the
attestation inputs on expiring dev images.
