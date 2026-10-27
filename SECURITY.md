# Security policy

## Reporting a vulnerability

Report it privately to vulnerability-report@wire.com; the PGP key and the
process are in Wire's
[global SECURITY.md](https://github.com/wireapp/wire/blob/master/SECURITY.md).
Do not open an issue or pull request for it.

Include what is affected (action, script, workflow, ref), how to reproduce it,
and its impact.

## Scope

In scope:

- the actions (every directory with an `action.yml`), their scripts and the
  reusable workflow `dev-build.yml`: for example a leak of a registry or
  release manager token, command or expression injection, a chart or image
  overwritten in the registry;
- this repository's own CI and release workflows, and the pinned tools they
  download.

Out of scope: the release manager service and the components that call these
actions (each follows its own security policy), and GitHub, quay.io or Helm
themselves.

Only the latest release is supported: fixes ship in a new release.
