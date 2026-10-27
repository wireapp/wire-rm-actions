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

1. `make release-prep VERSION=vX.Y.Z`: `dev-build.yml` calls the actions at
   `@vX.Y.Z`. Commit it through a pull request.
2. Once merged, tag the merge commit on `dev` with a signed annotated tag
   (`git tag -s vX.Y.Z -m vX.Y.Z`, SSH key listed in
   `.github/allowed_signers`) and push the tag.
3. The `Release` workflow checks the tag (vX.Y.Z, on `dev`, signature, the
   `dev-build.yml` refs) and creates a draft release.
4. A maintainer reviews the draft and publishes it.

Consumers then pin the tag's commit SHA (README, "Pin a release").
