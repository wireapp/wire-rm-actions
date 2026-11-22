# Contributing

## Setup

You need `bash`, `git`, `curl`, `python3` and GNU Make (3.81, the macOS one,
is enough).

```bash
make tools   # pinned shellcheck, actionlint, gitleaks; zizmor and pytest in .tools/venv
make hooks   # git hooks from .githooks: lint and secrets scan, commit message
make ci      # lint, audit, test, secrets-scan, commit-msg-check
```

`make` is the only entry point: the same targets run on a laptop, in the hooks
and in CI (one job per target).

The hooks are plain scripts in `.githooks` (`core.hooksPath`), without a hook
manager: for a bash repository this keeps one more tool out of the pinned set.

## Commit messages

One short first line, `<type>[(scope)][!]: <summary>`, summary 1 to 72
characters; types `feat fix docs build chore test refactor ci perf revert`.
The second line, when there is one, is empty. Merge commits pass. The
`commit-msg` hook and the `Commit messages` CI job check it
(`make commit-msg MSG=<file>`).

## Hard rules

- Secrets reach a step through `env:` or stdin only, never a command line.
- No `${{ }}` expression inside `run:`: pass the value through `env:`.
- Actions are pinned by full commit SHA, with the version in a comment:
  `uses: owner/action@<sha> # vX.Y.Z`.
- The action scripts source `scripts/lib.sh` (`die`, `warn`, `emit`,
  `summary`, `sha256_of`, `here`) instead of defining their own helpers.
- Tools are pinned with their sha256 (`scripts/install-tools.sh`), Python
  tools with their hashes (`requirements-ci.txt`, from `requirements-ci.in`).
- A published version is never overwritten (charts, tags, releases).
- No auto-merge: a maintainer merges.
- No new dependency (action, tool, package) without a written justification
  in the pull request.

## Release

This repository releases itself the way it asks components to
([docs/releasing.md](docs/releasing.md)): no artifact, so the release is the tagged
commit and its GitHub Release.

1. A release pull request on `dev`: `make release-prep VERSION=vX.Y.Z` points
   `dev-build.yml` at `@vX.Y.Z` (the exact tag: `vX.Y.Z-rc.N` for a
   pre-release, then again for the GA); `publication/release-note.md` and
   `publication/declaration.json` describe X.Y.Z (`make ci` validates them).
2. Once merged, run the `Prepare release` workflow on `dev` with the type and
   the bump that give that version (`minor` for X.Y.0; the default is `patch`). It
   checks the inputs, the CI of the commit, the three publication files and
   the pinned refs, and creates the draft release with the note, the
   declaration and the compatibility file; the body carries the changelog and
   the line consumers pin.
3. A release manager reviews the draft and approves the `release-publication`
   environment on that run. The publication checks the draft against its
   source commit and publishes it, which creates the tag `vX.Y.Z`.
4. If the run is gone, dispatch `Publish release` with the version: the draft
   is found by tag.
5. A candidate that went stale, or was rejected: delete its draft release,
   then prepare again. A draft counts as an existing release.

Consumers then pin the tag's commit SHA (README, "Pin a release").
