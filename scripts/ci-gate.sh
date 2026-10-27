#!/usr/bin/env bash
# The gates of a release preparation (ADR-0021 section 1): no release nor tag exists yet for
# the version, and the CI of the source commit passed. Two gates, each on or off:
#
#   release  no GitHub Release (draft or published) has the tag <TAG_PREFIX><VERSION>, and the
#            tag itself does not exist; never bypassed;
#   checks   the check runs and the legacy commit statuses of SOURCE_COMMIT passed. FORCE=true
#            skips this gate only, with a warning in the log and in the run summary.
#
# Each check run is judged by its LATEST outcome on the commit (a cancelled run superseded by
# a successful one passes), after excluding the runs of the calling workflow (its own check
# runs are attached to the commit it gates), of EXCLUDE_WORKFLOWS and of the GitHub-managed
# dynamic workflows (Dependabot). Which checks are required (CHECKS_FROM):
#
#   all           every check run on the commit: failure, timed_out,
#                 cancelled and action_required block, anything still running blocks, and an
#                 empty set blocks ("nothing ran" is never "everything passed"); legacy
#                 statuses block when their combined state is failure, error or pending;
#   list          the names in REQUIRED_CHECKS (check run name or status context);
#   branch-rules  the required status checks of the rulesets of BRANCH.
#   With list and branch-rules, each required check must be reported and pass like GitHub
#   branch protection judges it (success, neutral or skipped), other checks are ignored.
#
# Inputs (environment): GH_TOKEN, REPO (owner/name, default $GITHUB_REPOSITORY), VERSION,
# TAG_PREFIX (default v), SOURCE_COMMIT (full sha), RELEASE_GATE, CHECKS_GATE (default true),
# FORCE (default false), CHECKS_FROM (default all), REQUIRED_CHECKS (one per line), BRANCH,
# EXCLUDE_WORKFLOWS (workflow files, one per line, added to the calling one),
# EXCLUDE_DYNAMIC (default true), GITHUB_WORKFLOW_REF, GITHUB_RUN_ID.
#
# Outputs (stdout and $GITHUB_OUTPUT): tag, bypassed, checks-inspected, status-state.
set -euo pipefail
export LC_ALL=C
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

REPO="${REPO:-${GITHUB_REPOSITORY:-}}"
VERSION="${VERSION:-}"
TAG_PREFIX="${TAG_PREFIX-v}"
SOURCE_COMMIT="${SOURCE_COMMIT:-}"
RELEASE_GATE="${RELEASE_GATE:-true}"
CHECKS_GATE="${CHECKS_GATE:-true}"
FORCE="${FORCE:-false}"
CHECKS_FROM="${CHECKS_FROM:-all}"
REQUIRED_CHECKS="${REQUIRED_CHECKS:-}"
BRANCH="${BRANCH:-}"
EXCLUDE_WORKFLOWS="${EXCLUDE_WORKFLOWS:-}"
EXCLUDE_DYNAMIC="${EXCLUDE_DYNAMIC:-true}"

is_bool() {
  [[ "$1" == true || "$1" == false ]]
}

release_gate() {
  local tag="$1" ids ref
  ids="$(gh api --paginate "repos/${REPO}/releases?per_page=100" \
    | jq -rs --arg tag "$tag" '[(add // [])[] | select(.tag_name == $tag) | .id] | map(tostring) | join(", ")')" \
    || die "could not list the releases of ${REPO} (contents: read)"
  [[ -z "$ids" ]] || die "a draft or published release already exists for tag ${tag} (id(s): ${ids})"
  ref="$(gh api "repos/${REPO}/git/matching-refs/tags/${tag}" \
    | jq -r --arg ref "refs/tags/${tag}" '.[] | select(.ref == $ref) | .object.sha')" \
    || die "could not read the tags of ${REPO} (contents: read)"
  [[ -z "$ref" ]] || die "tag ${tag} already exists (${ref}): the version is taken"
  echo "No release and no tag ${tag}: safe to proceed."
}

# The workflow file names whose runs are excluded: the calling workflow and EXCLUDE_WORKFLOWS.
excluded_workflows() {
  local own line
  # Strip the @ref first: it contains slashes (@refs/heads/dev).
  own="${GITHUB_WORKFLOW_REF:-}"
  own="${own%%@*}"
  [[ -z "$own" ]] || basename "$own"
  while IFS= read -r line; do
    line="${line//[[:space:]]/}"
    [[ -z "$line" ]] || basename "$line"
  done <<<"$EXCLUDE_WORKFLOWS"
}

# The check runs of the commit, without the excluded runs, latest per name.
check_runs() {
  local all ids rid path wf workflows excluded='[]'
  all="$(gh api --paginate "repos/${REPO}/commits/${SOURCE_COMMIT}/check-runs?per_page=100" \
    | jq -cs '[.[].check_runs[]]')" || die "could not list the check runs of ${SOURCE_COMMIT} (checks: read)"
  workflows="$(excluded_workflows | sort -u)"
  ids="$(jq -r '[.[] | (.details_url // "") | capture("/actions/runs/(?<id>[0-9]+)(/|$)") | .id] | unique | .[]' <<<"$all")"
  while IFS= read -r rid; do
    [[ -n "$rid" ]] || continue
    if [[ "$rid" == "${GITHUB_RUN_ID:-}" ]]; then
      excluded="$(jq -c --arg id "$rid" '. + [$id]' <<<"$excluded")"
      echo "Excluding this run ${rid}" >&2
      continue
    fi
    path="$(gh api "repos/${REPO}/actions/runs/${rid}" | jq -r '.path // ""')" \
      || die "could not read workflow run ${rid} of ${REPO} (actions: read)"
    path="${path%%@*}"
    wf="$(basename "${path:-unknown}")"
    if [[ "$EXCLUDE_DYNAMIC" == true && "$path" == dynamic/* ]]; then
      excluded="$(jq -c --arg id "$rid" '. + [$id]' <<<"$excluded")"
      echo "Excluding GitHub-managed workflow run ${rid} (${path})" >&2
    elif [[ -n "$path" ]] && grep -Fxq -- "$wf" <<<"$workflows"; then
      excluded="$(jq -c --arg id "$rid" '. + [$id]' <<<"$excluded")"
      echo "Excluding workflow run ${rid} (${path})" >&2
    fi
  done <<<"$ids"
  jq -c --argjson excl "$excluded" '
    [ .[] | select(
        ((.details_url // "") | [capture("/actions/runs/(?<id>[0-9]+)(/|$)") | .id] | first) as $id
        | $id == null or ($excl | any(. == $id) | not)
      ) ]
    | [ group_by(.name)[] | max_by([(.started_at // ""), .id]) ]' <<<"$all"
}

gate_all() {
  local runs="$1" statuses="$2" bad pending count state status_count
  count="$(jq 'length' <<<"$runs")"
  bad="$(jq -r '.[] | select(.status == "completed" and (.conclusion | IN("failure", "timed_out", "cancelled", "action_required"))) | "  - \(.name): \(.conclusion)"' <<<"$runs")"
  pending="$(jq -r '.[] | select(.status != "completed") | "  - \(.name): \(.status)"' <<<"$runs")"
  [[ -z "$bad" ]] || { printf 'checks failed on %s:\n%s\n' "$SOURCE_COMMIT" "$bad" >&2; die "required checks failed on ${SOURCE_COMMIT}"; }
  [[ -z "$pending" ]] || { printf 'checks still running on %s:\n%s\n' "$SOURCE_COMMIT" "$pending" >&2; die "checks still running on ${SOURCE_COMMIT}"; }
  [[ "$count" -gt 0 ]] \
    || die "no check runs reported for ${SOURCE_COMMIT}: refusing to treat 'nothing ran' as 'everything passed'. Use force deliberately to override."
  # The combined state is "pending" for a commit without any status: only judged when one exists.
  status_count="$(jq -r '.total_count // 0' <<<"$statuses")"
  state="$(jq -r '.state // ""' <<<"$statuses")"
  if [[ "$status_count" -gt 0 ]]; then
    if [[ "$state" == failure || "$state" == error || "$state" == pending ]]; then
      jq -r '.statuses[]? | "  - \(.context): \(.state)"' <<<"$statuses" >&2
      die "combined status of ${SOURCE_COMMIT} is '${state}'"
    fi
  else
    state=none
  fi
  emit checks-inspected "$count"
  emit status-state "$state"
}

gate_required() {
  local runs="$1" statuses="$2" required="$3" problems
  [[ "$(jq 'length' <<<"$required")" -gt 0 ]] \
    || die "no required check to verify (checks-from ${CHECKS_FROM}): refusing to treat 'nothing required' as 'everything passed'. Use force deliberately to override."
  # Check runs first (latest per name), then the latest status of each context.
  problems="$(jq -rn --argjson runs "$runs" --argjson statuses "$statuses" --argjson required "$required" '
    $required[] as $name
    | ($runs | map(select(.name == $name)) | first) as $run
    | (($statuses.statuses // []) | map(select(.context == $name)) | first) as $status
    | if $run != null then
        if $run.status != "completed" then "  - \($name): \($run.status)"
        elif ($run.conclusion | IN("success", "neutral", "skipped")) then empty
        else "  - \($name): \($run.conclusion)" end
      elif $status != null then
        if $status.state == "success" then empty else "  - \($name): \($status.state)" end
      else "  - \($name): not reported" end')"
  if [[ -n "$problems" ]]; then
    printf 'required checks not passed on %s:\n%s\n' "$SOURCE_COMMIT" "$problems" >&2
    die "required checks not passed on ${SOURCE_COMMIT}"
  fi
  emit checks-inspected "$(jq 'length' <<<"$required")"
  emit status-state "$(jq -r 'if (.total_count // 0) > 0 then .state else "none" end' <<<"$statuses")"
}

required_list() {
  case "$CHECKS_FROM" in
    list)
      jq -Rsc 'split("\n") | map(gsub("^\\s+|\\s+$"; "")) | map(select(. != "")) | unique' <<<"$REQUIRED_CHECKS"
      ;;
    branch-rules)
      gh api --paginate "repos/${REPO}/rules/branches/${BRANCH}?per_page=100" \
        | jq -cs '[(add // [])[] | select(.type == "required_status_checks") | .parameters.required_status_checks[]?.context] | unique' \
        || die "could not read the rules of branch ${BRANCH} (contents: read)"
      ;;
  esac
}

checks_gate() {
  local runs statuses required
  if [[ "$FORCE" == true ]]; then
    summary "### :warning: CI gate bypassed" "" \
      "\`force: true\` was passed: the checks of \`${SOURCE_COMMIT}\` were NOT verified."
    echo "::warning title=CI gate bypassed::force=true: the checks of ${SOURCE_COMMIT} were NOT verified"
    emit bypassed true
    return
  fi
  emit bypassed false
  runs="$(check_runs)"
  statuses="$(gh api "repos/${REPO}/commits/${SOURCE_COMMIT}/status?per_page=100")" \
    || die "could not read the statuses of ${SOURCE_COMMIT} (statuses: read)"
  if [[ "$CHECKS_FROM" == all ]]; then
    gate_all "$runs" "$statuses"
  else
    required="$(required_list)"
    echo "Required checks (${CHECKS_FROM}): $(jq -r 'join(", ")' <<<"$required")"
    gate_required "$runs" "$statuses" "$required"
  fi
  echo "CI gate passed for ${SOURCE_COMMIT}."
  summary "> :white_check_mark: CI gate passed on \`${SOURCE_COMMIT}\` (checks-from \`${CHECKS_FROM}\`)."
}

main() {
  local tag
  [[ "$REPO" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || die "REPO '${REPO}' is not owner/name"
  is_bool "$RELEASE_GATE" || die "release-gate must be true or false (got: '${RELEASE_GATE}')"
  is_bool "$CHECKS_GATE" || die "checks-gate must be true or false (got: '${CHECKS_GATE}')"
  is_bool "$FORCE" || die "force must be true or false (got: '${FORCE}')"
  is_bool "$EXCLUDE_DYNAMIC" || die "exclude-dynamic must be true or false (got: '${EXCLUDE_DYNAMIC}')"
  [[ "$TAG_PREFIX" =~ ^[A-Za-z0-9._/-]*$ ]] || die "tag-prefix '${TAG_PREFIX}' has unexpected characters"
  case "$CHECKS_FROM" in
    all | list) ;;
    branch-rules) [[ "$BRANCH" =~ ^[A-Za-z0-9._/-]+$ ]] || die "branch-rules needs a branch (got: '${BRANCH}')" ;;
    *) die "checks-from must be all, list or branch-rules (got: '${CHECKS_FROM}')" ;;
  esac

  if [[ "$RELEASE_GATE" == true ]]; then
    [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] || die "VERSION '${VERSION}' is not a release version"
    tag="${TAG_PREFIX}${VERSION}"
    emit tag "$tag"
    release_gate "$tag"
  fi
  if [[ "$CHECKS_GATE" == true ]]; then
    [[ "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]] || die "SOURCE_COMMIT '${SOURCE_COMMIT}' is not a full commit sha"
    checks_gate
  fi
}

main "$@"
