#!/usr/bin/env bash
# The ADR-0018 version of a commit: the tag itself on a tag build, otherwise a
# dev build derived from the nearest GA or pre-release tag reachable from it.
#
#   nearest GA X.Y.Z            dev/release branch  X.Y.(Z+1)-<ts>.g<sha7>
#                               other branch        X.Y.(Z+1)-<ts>.<branch>.g<sha7>
#   nearest pre X.Y.Z-<pre>.N   dev/release branch  X.Y.Z-<pre>.N.<ts>.g<sha7>
#                               other branch        X.Y.Z-<pre>.N.<ts>.<branch>.g<sha7>
#
# <ts> is the committer date in UTC as YYYYMMDDHHMMSS, <sha7> the first 7
# characters of the commit, <branch> the last segment of the branch name,
# lowercased, non-alphanumerics replaced by '-', cut to 14 characters, without
# trailing '-'.
#
# Environment (all optional):
#   REF               commit to version (default HEAD)
#   BRANCH            branch the build runs for; required unless TAG is set
#   TAG               the tag of a tag build; the version is the tag itself
#   RELEASE_BRANCHES  regex of the dev/release branches
#                     (default ^(dev|develop|release/.+|release-.+)$)
#   TAG_PREFIX        prefix of the source tags (default v)
#
# Prints key=value lines (version, kind, base_tag, sha, branch_kind), and
# appends them to $GITHUB_OUTPUT when set.
set -euo pipefail
export LC_ALL=C
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

ref=${REF:-HEAD}
branch=${BRANCH:-}
tag=${TAG:-}
release_branches=${RELEASE_BRANCHES:-'^(dev|develop|release/.+|release-.+)$'}
prefix=${TAG_PREFIX-v}
max_length=63

num='(0|[1-9][0-9]*)'
ga_re="^${num}\\.${num}\\.${num}\$"
pre_re="^${num}\\.${num}\\.${num}-(alpha|beta|rc)\\.[1-9][0-9]*\$"

# The version a source tag names, or nothing when it is not GA nor pre-release.
tag_version() {
  local v=${1#"$prefix"}
  [[ $1 == "$prefix"* ]] || return 0
  if [[ $v =~ $ga_re || $v =~ $pre_re ]]; then
    echo "$v"
  fi
}

# The highest version among those tags: a GA above any pre-release.
highest() {
  local ga pre
  ga=$(grep -Ev -- '-' <<<"$1" || true)
  pre=$(grep -E -- '-' <<<"$1" || true)
  if [[ -n $ga ]]; then
    sort -V <<<"$ga" | tail -n1
  else
    sort -V <<<"$pre" | tail -n1
  fi
}

sha=$(git rev-parse --verify "${ref}^{commit}") || die "unknown commit: $ref"

if [[ -n $tag ]]; then
  version=$(tag_version "$tag")
  [[ -n $version ]] || die "tag $tag is neither a GA (${prefix}X.Y.Z) nor a pre-release (${prefix}X.Y.Z-alpha|beta|rc.N)"
  kind=ga
  [[ $version == *-* ]] && kind=prerelease
  emit version "$version"
  emit kind "$kind"
  emit base_tag "$tag"
  emit sha "$sha"
  emit branch_kind ""
  exit 0
fi

[[ -n $branch ]] || die "BRANCH is required for a dev build"
if [[ $(git rev-parse --is-shallow-repository) == true ]]; then
  die "shallow clone: check out with fetch-depth: 0 so the nearest tag is reachable"
fi

# Nearest GA or pre-release tag: git describe, skipping tags of another form.
excludes=()
while :; do
  nearest=$(git describe --tags --abbrev=0 --match "${prefix}[0-9]*" \
    ${excludes[@]+"${excludes[@]}"} "$sha" 2>/dev/null) ||
    die "no GA or pre-release tag (${prefix}X.Y.Z, ${prefix}X.Y.Z-alpha|beta|rc.N) is reachable from $sha"
  [[ -n $(tag_version "$nearest") ]] && break
  excludes+=(--exclude "$nearest")
done

# Several tags on that commit (rc.2 then the GA): the highest wins.
candidates=$(git tag --points-at "${nearest}^{commit}" | while read -r t; do tag_version "$t"; done)
base=$(highest "$candidates")
base_tag="${prefix}${base}"

ts=$(TZ=UTC0 git show -s --format=%cd --date=format-local:%Y%m%d%H%M%S "$sha")
suffix="${ts}"

if [[ $branch =~ $release_branches ]]; then
  branch_kind=release
else
  branch_kind=feature
  slug=$(printf '%s' "${branch##*/}" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | cut -c1-14 | sed 's/-*$//')
  [[ -n $slug ]] || die "branch $branch gives an empty <branch> identifier"
  [[ $slug =~ ^0[0-9]+$ ]] && die "branch $branch gives <branch> $slug: numeric with a leading zero, not valid SemVer"
  suffix="${suffix}.${slug}"
fi
suffix="${suffix}.g${sha:0:7}"

if [[ $base == *-* ]]; then
  version="${base}.${suffix}"
else
  IFS=. read -r major minor patch <<<"$base"
  version="${major}.${minor}.$((patch + 1))-${suffix}"
fi

((${#version} <= max_length)) || die "version $version is longer than $max_length characters (Helm limit)"

emit version "$version"
emit kind dev
emit base_tag "$base_tag"
emit sha "$sha"
emit branch_kind "$branch_kind"
