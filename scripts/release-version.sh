#!/usr/bin/env bash
# The next explicit release version of a branch (ADR-0018 grammar: X.Y.Z or
# X.Y.Z-<alpha|beta|rc>.N), for a prepare-release workflow; never for a dev
# build (compute-version.sh).
#
# Environment:
#   SOURCE_BRANCH     the trunk or a maintained release/X.Y line, resolvable as
#                     REMOTE/<branch> (required)
#   RELEASE_TYPE      ga | alpha | beta | rc (required)
#   VERSION_BUMP      patch | minor | major (default patch). From a GA anchor,
#                     the bump of the next GA or of the first pre-release. From
#                     a pre-release anchor, patch continues that pre-release
#                     and minor | major open a new line from its base
#                     (2.0.17-alpha.6 + minor -> 2.1.0-alpha.1 or 2.1.0)
#   EXPECTED_VERSION  optional: the version the release manager previewed. Never
#                     a source: the run fails, printing both values, when it
#                     differs from the result
#   REMOTE            git remote holding the branch (default origin)
#   TAG_PREFIX        prefix of the release tags (default v)
#
# Needs a checkout with the full tag history (fetch-depth: 0).
#
# Rules:
#   - anchor = the latest release tag <prefix>X.Y.Z[-...] reachable from
#     REMOTE/SOURCE_BRANCH (git describe; when several release tags point at
#     that commit, the highest in SemVer); other tags play no part;
#   - from a pre-release anchor with VERSION_BUMP patch: ga promotes its base,
#     the same channel increments N, a higher channel restarts at 1, a lower
#     channel is refused; the former form X.Y.Z-alphaNN is read but never
#     continued (SemVer sorts alpha.5 below alpha04);
#   - from a pre-release anchor with VERSION_BUMP minor or major: a new line
#     opens from the base of the anchor, <bump> for ga, <bump>-<channel>.1
#     otherwise, whatever the channel of the anchor;
#   - from a GA anchor: ga bumps per VERSION_BUMP, a pre-release is
#     <patch bump>-<channel>.1;
#   - release/X.Y may only produce X.Y.*; the target must not exist and no
#     release of the scanned scope (the line, or every release for the trunk)
#     may be ahead of it.
#
# Prints version=, kind= (ga | prerelease), tag=, latest-tag= (the anchor),
# from-tag= (changelog base: the preceding GA for a GA or the first release of
# a channel, the anchor otherwise) and sha= (the branch head), and appends them
# to $GITHUB_OUTPUT when set.
set -euo pipefail
export LC_ALL=C
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

SOURCE_BRANCH="${SOURCE_BRANCH:-}"
RELEASE_TYPE="${RELEASE_TYPE:-}"
VERSION_BUMP="${VERSION_BUMP:-patch}"
EXPECTED_VERSION="${EXPECTED_VERSION:-}"
REMOTE="${REMOTE:-origin}"
TAG_PREFIX="${TAG_PREFIX-v}"

SEMVER="$here/semver.sh"
readonly SEMVER
TAG_GLOB="${TAG_PREFIX}[0-9]*.[0-9]*.[0-9]*"
readonly TAG_GLOB

[[ -n "$SOURCE_BRANCH" ]] || die "SOURCE_BRANCH is required"
case "$RELEASE_TYPE" in
  ga | alpha | beta | rc) ;;
  *) die "RELEASE_TYPE must be one of ga, alpha, beta, rc (got: '$RELEASE_TYPE')" ;;
esac
case "$VERSION_BUMP" in
  patch | minor | major) ;;
  *) die "VERSION_BUMP must be one of patch, minor, major (got: '$VERSION_BUMP')" ;;
esac

rank() {
  case "$1" in
    alpha) echo 0 ;;
    beta) echo 1 ;;
    rc) echo 2 ;;
  esac
}

bump_version() { # <X.Y.Z> <patch|minor|major>
  local maj min pat
  IFS='.' read -r maj min pat <<<"$1"
  case "$2" in
    patch) echo "${maj}.${min}.$((pat + 1))" ;;
    minor) echo "${maj}.$((min + 1)).0" ;;
    major) echo "$((maj + 1)).0.0" ;;
  esac
}

branch_ref="refs/remotes/${REMOTE}/${SOURCE_BRANCH}"
git rev-parse --verify --quiet "$branch_ref" >/dev/null \
  || die "branch '${SOURCE_BRANCH}' is not available as ${REMOTE}/${SOURCE_BRANCH}"

# Latest explicit release (GA or pre-release) reachable from the branch.
latest_tag="$(git describe --tags --match "$TAG_GLOB" --abbrev=0 "$branch_ref" 2>/dev/null || true)"
[[ -n "$latest_tag" ]] \
  || die "no release tag ${TAG_PREFIX}* is reachable from '${SOURCE_BRANCH}': the first release of this history needs a tag on the last release commit"
# Several release tags on that commit (alpha.5 then alpha.6, rc.2 then the
# GA): the highest wins.
while IFS= read -r candidate_tag; do
  [[ -n "$candidate_tag" ]] || continue
  candidate="${candidate_tag#"$TAG_PREFIX"}"
  [[ "$candidate" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-(alpha|beta|rc)\.?[0-9]+)?$ ]] || continue
  if [[ "$("$SEMVER" compare "$candidate" "${latest_tag#"$TAG_PREFIX"}")" == 1 ]]; then
    latest_tag="$candidate_tag"
  fi
done < <(git tag -l "$TAG_GLOB" --points-at "${latest_tag}^{commit}")
latest="${latest_tag#"$TAG_PREFIX"}"

is_release_line=false
line=""
if [[ "$SOURCE_BRANCH" =~ ^release/([0-9]+\.[0-9]+)$ ]]; then
  is_release_line=true
  line="${BASH_REMATCH[1]}"
fi

target=""
if [[ "$latest" =~ ^([0-9]+\.[0-9]+\.[0-9]+)-(alpha|beta|rc)(\.?)([0-9]+)$ ]]; then
  latest_base="${BASH_REMATCH[1]}"
  latest_channel="${BASH_REMATCH[2]}"
  latest_legacy=false
  [[ -z "${BASH_REMATCH[3]}" ]] && latest_legacy=true
  latest_counter="${BASH_REMATCH[4]}"

  if [[ "$VERSION_BUMP" != patch ]]; then
    # An explicit minor or major bump leaves the pending pre-release behind
    # and opens a new line from its base.
    target="$(bump_version "$latest_base" "$VERSION_BUMP")"
    [[ "$RELEASE_TYPE" == ga ]] || target="${target}-${RELEASE_TYPE}.1"
    echo "version_bump '${VERSION_BUMP}' opens a new line: the pre-release ${latest_tag} stays unpromoted"
  elif [[ "$RELEASE_TYPE" == ga ]]; then
    # Promoting a pre-release fixes the version at its base.
    target="$latest_base"
  elif (( $(rank "$RELEASE_TYPE") < $(rank "$latest_channel") )); then
    die "cannot prepare '${RELEASE_TYPE}': the latest reachable release '${latest_tag}' is already at channel '${latest_channel}', which ranks higher; a release never moves backward in channel maturity for the same target version"
  elif [[ "$RELEASE_TYPE" == "$latest_channel" ]]; then
    if [[ "$latest_legacy" == true ]]; then
      die "cannot prepare '${RELEASE_TYPE}': the latest reachable release '${latest_tag}' uses the former pre-release form; '${latest_base}-${RELEASE_TYPE}.$((10#${latest_counter} + 1))' would sort below it in SemVer. Move to a higher channel or to GA instead"
    fi
    target="${latest_base}-${RELEASE_TYPE}.$((10#${latest_counter} + 1))"
  else
    target="${latest_base}-${RELEASE_TYPE}.1"
  fi
elif [[ "$latest" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  if [[ "$RELEASE_TYPE" == ga ]]; then
    target="$(bump_version "$latest" "$VERSION_BUMP")"
  else
    target="$(bump_version "$latest" "$VERSION_BUMP")-${RELEASE_TYPE}.1"
  fi
else
  die "could not parse the latest reachable release tag '${latest_tag}'"
fi

if [[ "$is_release_line" == true ]]; then
  target_line="$(grep -oE '^[0-9]+\.[0-9]+' <<<"$target")"
  [[ "$target_line" == "$line" ]] \
    || die "source branch 'release/${line}' may only produce ${line}.* releases; the computed target '${target}' falls outside that line (version_bump minor/major is invalid from a release/X.Y source)"
fi

if git rev-parse -q --verify "refs/tags/${TAG_PREFIX}${target}" >/dev/null; then
  die "tag '${TAG_PREFIX}${target}' already exists: refusing to recompute an existing release"
fi

# A maintenance line is expected to sit behind newer minors, so only its own
# tags can supersede its candidate; a trunk candidate must be the newest
# release overall.
if [[ "$is_release_line" == true ]]; then
  tag_scope="${TAG_PREFIX}${line}.*"
else
  tag_scope="$TAG_GLOB"
fi
while IFS= read -r existing_tag; do
  [[ -n "$existing_tag" ]] || continue
  existing="${existing_tag#"$TAG_PREFIX"}"
  [[ "$existing" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] || continue
  if [[ "$("$SEMVER" compare "$existing" "$target")" == 1 ]]; then
    die "existing tag '${existing_tag}' is already ahead of the computed target '${TAG_PREFIX}${target}': this candidate would be superseded or create a version gap"
  fi
done < <(git tag -l "$tag_scope")

# The changelog base: the preceding GA for a GA or the first release of a
# channel (the whole delta since the last GA), the anchor otherwise. Without
# any GA, the anchor.
if [[ "$RELEASE_TYPE" == ga || "$target" =~ -(alpha|beta|rc)\.1$ ]]; then
  from_tag="$(git describe --tags --exclude '*-*' --match "$TAG_GLOB" --abbrev=0 "$branch_ref" 2>/dev/null || echo "$latest_tag")"
else
  from_tag="$latest_tag"
fi

if [[ -n "$EXPECTED_VERSION" && "$EXPECTED_VERSION" != "$target" ]]; then
  die "the computed version '${target}' differs from expected_version '${EXPECTED_VERSION}': the release manager preview and this repository disagree, nothing was prepared"
fi

kind=ga
[[ "$target" == *-* ]] && kind=prerelease

echo "Next ${RELEASE_TYPE} release of ${SOURCE_BRANCH}: ${target} (after ${latest_tag}, changelog from ${from_tag})"
emit version "$target"
emit kind "$kind"
emit tag "${TAG_PREFIX}${target}"
emit latest-tag "$latest_tag"
emit from-tag "$from_tag"
emit sha "$(git rev-parse "$branch_ref")"
