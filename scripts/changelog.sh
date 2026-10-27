#!/usr/bin/env bash
# The changelog of the commits in FROM_REF..TO_REF, in the format
# components publish in their releases (generate-changelog 1.8.0): a
# "#### <version> (<date>)" heading, then one "##### <Type>" section per
# conventional commit type, sorted by type, commits newest first, grouped by
# scope, with commit and pull request links.
#
#   feat(api): add x (#12)     ->  * **api:** add x ([#12](<repo>/pull/12)) ([abcdef01](<repo>/commit/<sha>))
#   fix: y [breaking]          ->  section "Breaking Changes"
#   (merge-commits=pull-request) a commit under "Merge pull request #12" gets
#                                  ([#12](<repo>/pull/12)) before its commit link
#   anything without "type:"   ->  left out
#
# Environment:
#   FROM_REF     the previous release tag (required); its commits are excluded
#   TO_REF       last commit included (default HEAD)
#   VERSION      version in the heading (default none: "#### <date>")
#   REPO_URL     https://github.com/<owner>/<repo>, for the links (default none)
#   EXCLUDE      types left out, comma or space separated
#                (default chore build docs refactor style test runfix)
#   HEADING      false drops the heading line (default true)
#   MERGE_COMMITS  ignore (default) or pull-request: with pull-request, the
#                commits brought in by a "Merge pull request #N from ..." merge
#                get the link of that pull request (a squash or rebase merge
#                already has "(#N)" in the subject); the merge itself is left
#                out either way
#   COLLAPSE     types whose section is folded in a <details> block after the
#                other sections, comma or space separated (default none);
#                Breaking Changes is never folded
#   OUTPUT_FILE  where the changelog is written (default CHANGELOG.md)
#   DATE         heading date, YYYY-MM-DD (default today, UTC)
#
# Prints key=value lines (file, count), and appends them to $GITHUB_OUTPUT
# when set.
set -euo pipefail
export LC_ALL=C
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

from=${FROM_REF:-}
to=${TO_REF:-HEAD}
version=${VERSION:-}
repo_url=${REPO_URL:-}
exclude=${EXCLUDE-chore build docs refactor style test runfix}
heading=${HEADING:-true}
merge_commits=${MERGE_COMMITS:-ignore}
collapse=${COLLAPSE-}
output=${OUTPUT_FILE:-CHANGELOG.md}
date=${DATE:-$(date -u +%Y-%m-%d)}

[[ -n $from ]] || die "FROM_REF is required"
[[ $date =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || die "DATE must be YYYY-MM-DD: $date"
[[ $heading == true || $heading == false ]] || die "HEADING must be true or false: $heading"
[[ $merge_commits == ignore || $merge_commits == pull-request ]] ||
  die "MERGE_COMMITS must be ignore or pull-request: $merge_commits"
[[ -z ${collapse//[a-z ,]/} ]] || die "COLLAPSE must list commit types, comma or space separated: $collapse"
[[ " ${collapse//,/ } " != *" breaking "* ]] || die "COLLAPSE cannot fold the breaking changes"
[[ -z $repo_url || $repo_url =~ ^https://[A-Za-z0-9.-]+(/[A-Za-z0-9._-]+)+$ ]] ||
  die "REPO_URL must be https://<host>/<owner>/<repo>: $repo_url"
[[ -z $version || $version =~ ^[0-9A-Za-z.+-]+$ ]] || die "invalid VERSION: $version"
if [[ $(git rev-parse --is-shallow-repository) == true ]]; then
  die "shallow clone: check out with fetch-depth: 0 so $from is reachable"
fi
from_sha=$(git rev-parse --verify --quiet --end-of-options "${from}^{commit}") || die "unknown ref: $from"
to_sha=$(git rev-parse --verify --quiet --end-of-options "${to}^{commit}") || die "unknown ref: $to"

# One commit per line: sha, unit separator, subject.
log=$(git log --no-color --format='%H%x1f%s' "${from_sha}..${to_sha}")

count_file=$(mktemp)
pr_file=$(mktemp)
trap 'rm -f "$count_file" "$pr_file"' EXIT

# "<sha> <pr>" for every commit a "Merge pull request #N" merge brought in,
# oldest merge first: a commit keeps the first pull request that carried it.
if [[ $merge_commits == pull-request ]]; then
  merge_re='^Merge pull request #([1-9][0-9]*)( |$)'
  while IFS=$'\x1f' read -r _ parents subject; do
    [[ $subject =~ $merge_re ]] || continue
    read -r -a parent <<<"$parents"
    ((${#parent[@]} == 2)) || continue
    git rev-list "${parent[0]}..${parent[1]}" | awk -v pr="${BASH_REMATCH[1]}" '{ print $1, pr }' >>"$pr_file"
  done < <(git log --no-color --merges --reverse --format='%H%x1f%P%x1f%s' "${from_sha}..${to_sha}")
fi

printf '%s\n' "$log" | awk \
  -v repo_url="$repo_url" \
  -v exclude="$exclude" \
  -v collapse="$collapse" \
  -v pr_file="$pr_file" \
  -v heading="$heading" \
  -v title="${version:+$version (}${date}${version:+)}" \
  -v count_file="$count_file" '
BEGIN {
  FS = sprintf("%c", 31)
  split("breaking build chore ci docs feat fix other perf refactor revert style test", order, " ")
  names["breaking"] = "Breaking Changes"
  names["build"] = "Build System / Dependencies"
  names["ci"] = "Continuous Integration"
  names["chore"] = "Chores"
  names["docs"] = "Documentation Changes"
  names["feat"] = "New Features"
  names["fix"] = "Bug Fixes"
  names["other"] = "Other Changes"
  names["perf"] = "Performance Improvements"
  names["refactor"] = "Refactors"
  names["revert"] = "Reverts"
  names["style"] = "Code Style Changes"
  names["test"] = "Tests"
  gsub(/,/, " ", exclude)
  n = split(exclude, ex, " ")
  for (i = 1; i <= n; i++) excluded[ex[i]] = 1
  gsub(/,/, " ", collapse)
  n = split(collapse, co, " ")
  for (i = 1; i <= n; i++) folded[co[i]] = 1
  while ((getline line < pr_file) > 0) {
    split(line, pair, " ")
    if (!(pair[1] in pull)) pull[pair[1]] = pair[2]
  }
  close(pr_file)
  kept = 0
}

function trim(s) {
  sub(/^[ \t\r\n\f\v]+/, "", s)
  sub(/[ \t\r\n\f\v]+$/, "", s)
  return s
}

function replace_all(s, from, to,    out, at) {
  out = ""
  while ((at = index(s, from)) > 0) {
    out = out substr(s, 1, at - 1) to
    s = substr(s, at + length(from))
  }
  return out s
}

# Any contributor writes the commit subjects: no link, image, HTML nor
# autolink of theirs reaches the release body: a link or an image needs "](",
# HTML and autolinks "<". Plain text replacement, no regex: the same with
# every awk. A hex entity: link_prs would turn the "#40" of "&#40;" into a link.
function neutralize(s) {
  s = replace_all(s, "<", "&lt;")
  s = replace_all(s, ">", "&gt;")
  return replace_all(s, "](", "]&#x28;")
}

# "#123" -> "[#123](<repo>/pull/123)", as generate-changelog does.
function link_prs(s,    out, num) {
  if (repo_url == "") return s
  out = ""
  while (match(s, /#[1-9][0-9]*/)) {
    num = substr(s, RSTART + 1, RLENGTH - 1)
    out = out substr(s, 1, RSTART - 1) "[#" num "](" repo_url "/pull/" num ")"
    s = substr(s, RSTART + RLENGTH)
  }
  return out s
}

# The subject pattern of generate-changelog:
#   ^([^)]*)(?:\(([^)]*?)\)|):(.*?(?:\[([^\]]+?)\]|))\s*$
# The greedy type ends at the last ":" (or "(scope):") before the first ")".
{
  sha = $1
  subject = substr($0, length(sha) + 2)
  if (sha == "") next
  len = length(subject)
  close_at = index(subject, ")")
  limit = close_at ? close_at - 1 : len
  type = ""; scope = ""; rest = ""; found = 0
  for (k = limit; k >= 1; k--) {
    c = substr(subject, k, 1)
    if (c == ":") {
      type = substr(subject, 1, k - 1); rest = substr(subject, k + 1); found = 1; break
    }
    if (c == "(" && close_at && substr(subject, close_at + 1, 1) == ":") {
      type = substr(subject, 1, k - 1)
      scope = substr(subject, k + 1, close_at - k - 1)
      rest = substr(subject, close_at + 2); found = 1; break
    }
  }
  if (!found || type == "") next
  sub(/[ \t\r\n\f\v]+$/, "", rest)
  if (rest == "") next
  type = tolower(type)
  if (match(rest, /\[[^]]+\][ \t\r\n\f\v]*$/)) {
    nflags = split(tolower(substr(rest, RSTART + 1, RLENGTH - 2)), flags, ",")
    for (i = 1; i <= nflags; i++) if (trim(flags[i]) == "breaking") type = "breaking"
  }
  if (type in excluded) next
  scope = neutralize(scope)
  rest = neutralize(rest)
  section = (type in names) ? type : "other"
  key = section SUBSEP scope
  number = (sha in pull) ? pull[sha] : ""
  linked = (number != "" && rest ~ ("#" number "([^0-9]|$)"))
  if (!(key in items)) {
    nscopes[section]++
    scopes[section, nscopes[section]] = scope
    items[key] = 0
  }
  items[key]++
  short = substr(sha, 1, 8)
  if (repo_url != "") {
    short = "[" short "](" repo_url "/commit/" sha ")"
    rest = link_prs(rest)
  }
  if (number != "" && !linked) {
    rest = rest " (" (repo_url != "" ? "[#" number "](" repo_url "/pull/" number ")" : "#" number) ")"
  }
  entry[key, items[key]] = rest " (" short ")"
  total[section]++
  kept++
}

function emit_section(section,    s, scope, key, prefix, i, fold) {
  fold = (section in folded)
  if (fold) {
    print "<details>"
    print "<summary>" names[section] " (" total[section] ")</summary>"
  } else {
    print "##### " names[section]
  }
  print ""
  for (s = 1; s <= nscopes[section]; s++) {
    scope = scopes[section, s]
    key = section SUBSEP scope
    prefix = "*" (scope != "" ? " **" scope ":**" : "")
    if (items[key] > 1 && scope != "") {
      print prefix
      prefix = "  *"
    }
    for (i = 1; i <= items[key]; i++) print prefix " " entry[key, i]
  }
  print ""
  if (fold) {
    print "</details>"
    print ""
  }
}

END {
  if (heading == "true") { print "#### " title; print "" }
  # The folded sections come last: what readers act on stays on top.
  for (o = 1; o <= 13; o++) {
    section = order[o]
    if ((section in nscopes) && !(section in folded)) emit_section(section)
  }
  for (o = 1; o <= 13; o++) {
    section = order[o]
    if ((section in nscopes) && (section in folded)) emit_section(section)
  }
  print kept > count_file
}' >"$output"

emit file "$output"
emit count "$(cat "$count_file")"
