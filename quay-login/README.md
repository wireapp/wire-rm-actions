[wire-rm-actions](../README.md) ·
[version](../version/README.md) ·
[build-image](../build-image/README.md) ·
**quay-login** ·
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

# quay-login

> Log in to quay.io with the OIDC token of the job, through a federated robot
> account: no robot password in the repository, nothing to rotate.

## Definition

Quay 3.16 lets a robot account of an organization trust an external OIDC
issuer ("robot identity federation"). `quay-login` asks GitHub for the OIDC
token of the running job, exchanges it at
`https://quay.io/oauth2/federation/robot/token` for a robot token valid one
hour, runs `docker login` with it and outputs it for the tools that log in
themselves (`helm registry login`, `crane auth login`, `oras login`).

Quay only accepts the exchange when the token's issuer and subject match a
federation entry of the robot: a job of another repository, branch or
environment gets nothing, and a stolen token is worth a few minutes.

## Technical reference

### Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `robot` | yes | | The federated robot account, `<organization>+<name>` (e.g. `wire+gha_my-component`). |
| `registry` | no | `quay.io` | Registry host. |
| `audience` | no | `quay` | The OIDC audience the federation accepts (the *OIDC audiences* field of the robot). |
| `docker-login` | no | `true` | Also run `docker login` with the robot token. |

### Outputs

| Output | Description |
|---|---|
| `token` | The robot token (masked, valid one hour). |
| `username` | The robot account, to pair with `token`. |

### Requirements

- The job has `permissions: id-token: write` (job level, with the other
  permissions of the job: `permissions` at job level replaces the workflow's).
- The robot is a robot account of a Quay **organization** (federation does
  not exist for robots of user accounts), with Write on the repositories the
  job pushes to.
- The robot federation lists the issuer `https://token.actions.githubusercontent.com`,
  the exact subject of the job and the audience (`quay`).

### Subjects

The subject is the `sub` claim of the job's token. Without customization:

| Job | Subject |
|---|---|
| with `environment: release-publication` | `repo:<owner>/<repo>:environment:release-publication` |
| on a branch, no environment | `repo:<owner>/<repo>:ref:refs/heads/<branch>` |
| on a tag, no environment | `repo:<owner>/<repo>:ref:refs/tags/<tag>` |

One entry per subject: a dev build on `dev` and on each `release/X.Y` branch
needs its own line (no wildcards). Repositories created after July 2026, or
opted in to immutable subjects, use `repo:<owner>@<id>/<repo>@<id>:…`: read
the exact value in *Settings › Actions › OIDC* of the repository.

### Example

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write   # the OIDC token of the job, for quay-login
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 0
          persist-credentials: false
      - id: version
        uses: wireapp/wire-rm-actions/version@<sha>
      - id: quay
        uses: wireapp/wire-rm-actions/quay-login@<sha>
        with:
          robot: wire+gha_my-component
      - uses: docker/build-push-action@c3c9e263c25d99ce0380d002d59b67737d91b0dc # v7.4.0
        with:
          push: true
          tags: quay.io/wire/my-component:${{ steps.version.outputs.version }}
      - id: chart
        uses: wireapp/wire-rm-actions/publish-chart@<sha>
        with:
          chart-path: charts/my-component
          version: ${{ steps.version.outputs.version }}
          username: ${{ steps.quay.outputs.username }}
          password: ${{ steps.quay.outputs.token }}
```

The robot token lasts one hour: call `quay-login` after a long build, right
before the pushes, or call it again.

## Design notes

- **Fails closed.** Unlike [notify-rm](../notify-rm/README.md), a login that
  fails stops the job: a build that cannot push has nothing to declare.
- **Tokens on stdin only.** The runner's request token, the OIDC token and the
  robot token reach `curl` and `docker` through stdin (a curl config, a
  password prompt), never on a command line, and are masked before anything
  else is printed. A refusal prints a filtered excerpt of Quay's error, never
  its body.
- **No logout.** The docker login lives in the runner's docker config until
  the end of the job, as `docker/login-action` does; the token is dead one
  hour later anyway. On a self-hosted runner, add a `docker logout` step.
- **No third-party action.** The exchange is two `curl` calls; the action
  needs `curl`, `jq` and `docker`, all on the GitHub runners.
