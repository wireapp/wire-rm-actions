[wire-rm-actions](../README.md) ·
[version](../version/README.md) ·
[build-image](../build-image/README.md) ·
[quay-login](../quay-login/README.md) ·
[publish-chart](../publish-chart/README.md) ·
**notify-rm** ·
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

# notify-rm

> Declare a built version, dev build or release, to the staging and prod
> release managers.

## Definition

`notify-rm` sends one record to `POST /api/v1/versions` of every release
manager whose URL is set, with source `chart-release`: the component, the
version, where the artifact lives and where it comes from. Releases add their
date, their release note and, optionally, their
[release declaration](../release-declaration/README.md).

## Technical reference

### Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `component` | yes | | Release manager component id. |
| `version` | yes | | The version, from [version](../version/README.md). |
| `kind` | no | `dev` | `dev`, `ga` or `prerelease` (sent as `meta.build`). |
| `rm-staging-url` | no | `""` | Staging release manager base URL. Empty skips it with a warning. |
| `rm-staging-token` | no | `""` | Ingest token of the staging release manager, bound to the component. |
| `rm-prod-url` | no | `""` | Prod release manager base URL. Empty skips it with a warning. |
| `rm-prod-token` | no | `""` | Ingest token of the prod release manager, bound to the component. |
| `rm-staging-audience` | no | `""` | [OIDC mode](#oidc-mode-no-token-to-store): the audience of the staging release manager (e.g. `wire-release-manager-staging`). Used when `rm-staging-token` is empty. |
| `rm-prod-audience` | no | `""` | The same for the prod release manager (e.g. `wire-release-manager-prod`). |
| `repository` | no | `""` | `oci://…` repository of the artifact, from [publish-chart](../publish-chart/README.md). |
| `digest` | no | `""` | `sha256:…` digest of the artifact, from [publish-chart](../publish-chart/README.md). |
| `release-url` | no | `""` | The component's release page (GA and pre-release builds). |
| `released-at` | no | `""` | Release date `YYYY-MM-DD` (GA and pre-release builds, write-once). |
| `release-note-title` | no | `""` | Release note title, e.g. `vX.Y.Z`. |
| `release-note-description` | no | `""` | Release note body (markdown), e.g. the GitHub release body. |
| `meta` | no | `""` | Extra version tags, one `key=value` per line. |
| `release-declaration-file` | no | `""` | Path of a release declaration (JSON object), sent as `release_declaration`. |
| `release-manifest-file` | no | `""` | Path of the release manifest (JSON object, ADR-0020 §2), sent as `manifest`: the release manager derives the version's requirements and provides from its `compatibility`. |
| `required` | no | `"false"` | `"true"` fails the step when a declaration fails. |

No outputs. Each release manager gets one line in the job summary: declared,
skipped or not declared, and why.

### The record

```json
[{
  "component_id": "my-component",
  "component_version": "4.24.3-20261005135125.gabcdef0",
  "source": "chart-release",
  "app_version": "4.24.3-20261005135125.gabcdef0",
  "repository": "oci://quay.io/wire/charts/dev/my-component",
  "digest": "sha256:4f1c…",
  "meta": {
    "build": "dev",
    "commit": "abcdef0…",
    "branch": "dev",
    "run": "https://github.com/wireapp/my-component/actions/runs/123"
  }
}]
```

Empty inputs are left out of the record. `release_url`, `released_at`,
`release_note` and `release_declaration` appear when given; `meta` lines are
added to `meta`.

### Requirements

- `bash`, `curl` and `jq` (all GitHub-hosted runners).
- The component exists in the release manager, and the declared repository
  matches its artifact name.
- One ingest token per release manager and per repository (scope `ingest`,
  bound to the component), stored as a repository secret, **or** the
  [OIDC mode](#oidc-mode-no-token-to-store): an audience and
  `permissions: id-token: write`, with the repository bound to its components in
  the release manager.

### OIDC mode: no token to store

With an audience set and the matching token input empty, the step asks GitHub
for an OIDC token of the running job (`ACTIONS_ID_TOKEN_REQUEST_URL`, with
`&audience=<audience>`, through `curl`) and sends it as the `Bearer`, instead of
an ingest token kept in a repository secret. The release manager checks the
token and the repository it comes from, and lets it declare only the components
that repository is bound to.

- **The caller needs `permissions: id-token: write`, at job level only**, never
  at workflow level: that permission lets every step of the job request tokens.
  Without it the step warns (`the job lacks permissions: id-token: write`) and
  declares nothing, like any other `notify-rm` error (it fails the step only with
  `required: "true"`).
- A token input that is set always wins: the two modes can be mixed, for example
  OIDC to staging while prod still has its token.
- The OIDC token is masked in the log (`::add-mask::`) the moment it is received
  and never printed; the runner's own request token goes to `curl` on stdin. The
  token endpoint answer is never shown. The audience is URL-encoded.
- The release manager URL is as sensitive in this mode as the ingest token was: an
  OIDC token is sent to whatever `rm-*-url` says, so keep that variable under the same
  review as a secret (anyone who can change it can have a token sent elsewhere for
  the few minutes it lives).
- Use one audience per release manager instance, never a URL: GitHub issues a URL
  audience by default and the release manager refuses it.
- The token endpoint must be `https://` (`http://` only for loopback tests), and
  the OIDC token goes only to a release manager that passes the same URL check.

### Behaviour

- **URL unset or empty**: that release manager is skipped with a warning.
- **URL**: `https://` only. `http://` is accepted for `127.0.0.1` and
  `localhost` (tests); any other URL is a failed declaration.
- **Token**: sent as `Authorization: Bearer`, through a curl config on stdin,
  never on a command line.
- **Transport**: 3 retries, 60 s timeout, no redirect: an SSO page answering
  `3xx` is reported as such, not followed.
- **Logs**: the script never prints the release manager URL: messages name
  `rm-staging` and `rm-prod`, the URL and its host are masked (`::add-mask::`)
  before the first request, and the errors of `curl`, which name the host, are not
  shown, only its exit status. The runner itself prints the `with:` inputs of every
  step before the script starts, and masks only secrets: **a URL given as
  `${{ vars.… }}` appears in clear in the job log**. In a public repository, keep
  the URLs in secrets (`${{ secrets.RM_STAGING_URL }}`), which the runner masks.
  The reusable workflow [dev-build](../.github/workflows/dev-build.yml) reads the
  `RM_STAGING_URL` and `RM_PROD_URL` variables, so with it the URLs are visible:
  in a public component, call `notify-rm` yourself.
- **Success**: any `2xx`. Otherwise the response body (500 bytes at most) is
  shown in the log, never interpreted as workflow commands.
- **Release declaration file** missing or not a JSON object: a failed
  declaration, and nothing is sent anywhere.
- **Failure**: a warning, so a release manager outage never breaks a build,
  unless `required: "true"`.

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
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 0
          persist-credentials: false
      - uses: azure/setup-helm@9bc31f4ebc9c6b171d7bfbaa5d006ae7abdb4310 # v5.0.1
        with:
          version: v4.3.0
      - id: version
        uses: wireapp/wire-rm-actions/version@<sha> # vX.Y.Z
      - id: chart
        uses: wireapp/wire-rm-actions/publish-chart@<sha> # vX.Y.Z
        with:
          chart-path: charts/my-chart
          version: ${{ steps.version.outputs.version }}
          username: ${{ secrets.QUAY_USER }}
          password: ${{ secrets.QUAY_TOKEN }}
      - uses: wireapp/wire-rm-actions/notify-rm@<sha> # vX.Y.Z
        with:
          rm-staging-url: ${{ secrets.RM_STAGING_URL }}
          rm-staging-token: ${{ secrets.RM_STAGING_TOKEN }}
          rm-prod-url: ${{ secrets.RM_PROD_URL }}
          rm-prod-token: ${{ secrets.RM_PROD_TOKEN }}
          component: my-component
          version: ${{ steps.version.outputs.version }}
          kind: ${{ steps.version.outputs.kind }}
          repository: ${{ steps.chart.outputs.repository }}
          digest: ${{ steps.chart.outputs.digest }}
```

### Example: OIDC to staging

```yaml
jobs:
  declare:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write # the OIDC token of this job, nothing else
    steps:
      - uses: wireapp/wire-rm-actions/notify-rm@<sha> # vX.Y.Z
        with:
          rm-staging-url: ${{ secrets.RM_STAGING_URL }}
          rm-staging-audience: wire-release-manager-staging
          component: my-component
          version: ${{ needs.build.outputs.version }}
```

## Design notes

**A declaration is a fact, not a judgment.** The record says that a version
exists, where its artifact is and which commit and run produced it. Whether it
is good enough for a bundle is the release manager's call, made later, by
people.

**The release manager never breaks a build.** An outage, an expired token or
a missing URL only warns: building and publishing stay independent of the
release manager. A pipeline that must not go on without its declaration says
so with `required: "true"`.

**Staging and prod hear the same story.** One record, sent to every release
manager whose URL is set, so the two never disagree on what was built.

**No stored secret is the narrower token.** In OIDC mode nothing is kept in the
repository: the token lives for minutes, names the repository, the workflow and
the commit, and the release manager decides from those claims, not from a
secret that can leak.

**Tokens are narrow and well kept.** One token per repository, bound to its
components: a leaked token cannot write another team's versions. It travels
on stdin to curl, over HTTPS only, and is never followed to another host by a
redirect.
