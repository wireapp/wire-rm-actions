#!/usr/bin/env bash
# The source of a release candidate (ADR-0021 section 3), the preamble of a prepare-release
# workflow. Three modes, selected by MODE:
#
#   verify   before the checkout: the source branch exists on the repository; when it does not,
#            the job summary lists the release lines that do, and the run fails;
#   resolve  after a checkout of the branch with fetch-depth 0: the commit the candidate is
#            built from, recorded now so that a later move of the branch changes nothing;
#   summary  once the version is known: the job summary identifies the candidate (table,
#            commits since the previous release) while preparation is still in progress.
#
# Environment:
#   SOURCE_BRANCH   the branch to release from (all modes), [A-Za-z0-9._/-]+
# verify:
#   REPO            owner/name (default $GITHUB_REPOSITORY)
#   GH_TOKEN        read access to the repository
# summary:
#   VERSION, RELEASE_TYPE, SOURCE_SHA (full), BASE_TAG (latest release reachable), FROM_TAG
#   (the changes are those since this tag), all required
#   TAG_PREFIX      prefix of the git tag, shown before the version (default: v)
#   NOTE            a trailing line of the summary (default: none)
#   COMMITS         true | false (default true): list the commits FROM_TAG..SOURCE_SHA
#
# Outputs (stdout and $GITHUB_OUTPUT): resolve: sha; summary: commit-count.
set -euo pipefail
export LC_ALL=C
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

MODE="${MODE:-}"
SOURCE_BRANCH="${SOURCE_BRANCH:-}"

# check_branch: the name reaches an API path and a git ref.
check_branch() {
  [[ -n "$SOURCE_BRANCH" ]] || die "source_branch is required"
  [[ "$SOURCE_BRANCH" =~ ^[A-Za-z0-9._/-]+$ && "$SOURCE_BRANCH" != *..* ]] \
    || die "source_branch '${SOURCE_BRANCH}' is not a branch name"
}

verify() {
  local repo="${REPO:-${GITHUB_REPOSITORY:-}}" lines=() line

  check_branch
  [[ "$repo" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ && "$repo" != ./* && "$repo" != ../* && "$repo" != */. && "$repo" != */.. ]] \
    || die "repository '${repo}' is not owner/name"

  if gh api "repos/${repo}/branches/${SOURCE_BRANCH}" --jq '.name' >/dev/null 2>&1; then
    echo "Source branch '${SOURCE_BRANCH}' exists."
    return
  fi

  # Best effort: the listing may fail too, the run fails either way.
  while IFS= read -r line; do
    lines+=("- ${line}")
  done < <(gh api --paginate "repos/${repo}/branches" --jq '.[].name | select(startswith("release/"))' 2>/dev/null || true)
  summary \
    "### :x: Source branch does not exist" \
    "" \
    "\`${SOURCE_BRANCH}\` does not exist on \`${repo}\`. Release lines that currently exist:" \
    ${lines[@]+"${lines[@]}"}
  die "branch '${SOURCE_BRANCH}' does not exist on ${repo}"
}

resolve() {
  local sha tip

  check_branch
  sha="$(git rev-parse HEAD)"
  tip="$(git rev-parse --verify -q "refs/remotes/origin/${SOURCE_BRANCH}^{commit}")" \
    || die "branch '${SOURCE_BRANCH}' is not in the checkout (fetch-depth 0, branch fetched)"
  [[ "$tip" == "$sha" ]] \
    || die "the checkout is at ${sha}, not at the tip of origin/${SOURCE_BRANCH} (${tip})"
  # Record the exact commit now: a later move of the branch must not change the candidate.
  echo "Resolved source_branch '${SOURCE_BRANCH}' to ${sha}"
  emit sha "$sha"
}

summarise() {
  local version="${VERSION:-}" release_type="${RELEASE_TYPE:-}" sha="${SOURCE_SHA:-}"
  local base_tag="${BASE_TAG:-}" from_tag="${FROM_TAG:-}" prefix="${TAG_PREFIX-v}"
  local note="${NOTE:-}" commits="${COMMITS:-true}" count line
  local lines=()

  check_branch
  [[ -n "$version" ]] || die "version is required"
  [[ -n "$release_type" ]] || die "release_type is required"
  [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || die "source_sha '${sha}' is not a full sha"
  [[ -n "$base_tag" ]] || die "base_tag is required"
  [[ "$from_tag" =~ ^[A-Za-z0-9][A-Za-z0-9._/+-]*$ ]] || die "from_tag '${from_tag}' is not a tag name"
  [[ "$prefix" =~ ^[A-Za-z0-9._/-]*$ ]] || die "tag_prefix '${prefix}' is not a tag prefix"
  case "$commits" in
    true | false) ;;
    *) die "commits must be true or false (got: '${commits}')" ;;
  esac

  count="$(git rev-list --count "${from_tag}..${sha}")"

  lines+=(
    "## Preparing \`${prefix}${version}\`"
    ""
    "| | |"
    "| --- | --- |"
    "| Version | \`${version}\` |"
    "| Channel | \`${release_type}\` |"
    "| Source branch | \`${SOURCE_BRANCH}\` |"
    "| Source commit | \`${sha}\` |"
    "| Anchor (latest release reachable) | \`${base_tag}\` |"
    "| Changes since | \`${from_tag}\` |"
  )
  if [[ "$commits" == true ]]; then
    lines+=("" "<details>" "<summary>Commits since ${from_tag}</summary>" "")
    if ((count == 0)); then
      lines+=("_No commits since ${from_tag}._")
    else
      while IFS= read -r line; do
        lines+=("$line")
      done < <(git log --format='- %h %s' "${from_tag}..${sha}")
    fi
    lines+=("" "</details>")
  fi
  if [[ -n "$note" ]]; then
    lines+=("" "$note")
  fi
  summary "${lines[@]}"

  echo "Summarised ${prefix}${version} (${count} commits since ${from_tag})"
  emit commit-count "$count"
}

case "$MODE" in
  verify) verify ;;
  resolve) resolve ;;
  summary) summarise ;;
  *) die "MODE must be verify, resolve or summary (got: '$MODE')" ;;
esac
