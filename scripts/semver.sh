#!/usr/bin/env bash
# SemVer 2.0 precedence in plain bash, for the release scripts (the runners have
# no `semver` binary).
#
# Usage:
#   semver.sh compare <a> <b>   prints -1, 0 or 1 (a < b, a == b, a > b); exits 1
#                               on an invalid version
#   semver.sh valid <a>         exits 0 when <a> is a valid SemVer version, 1 otherwise
#
# Build metadata (+...) is ignored in comparisons, as the specification says.
set -euo pipefail
export LC_ALL=C
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

readonly SEMVER_RE='^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-([0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*))?(\+[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$'

# compare_identifiers <a> <b>: one pre-release identifier each. Numeric ones
# compare as numbers and rank below alphanumeric ones, which compare in ASCII
# order.
compare_identifiers() {
  local a="$1" b="$2"
  if [[ "$a" =~ ^[0-9]+$ && "$b" =~ ^[0-9]+$ ]]; then
    if (( 10#$a < 10#$b )); then echo -1; elif (( 10#$a > 10#$b )); then echo 1; else echo 0; fi
  elif [[ "$a" =~ ^[0-9]+$ ]]; then
    echo -1
  elif [[ "$b" =~ ^[0-9]+$ ]]; then
    echo 1
  elif [[ "$a" < "$b" ]]; then
    echo -1
  elif [[ "$a" > "$b" ]]; then
    echo 1
  else
    echo 0
  fi
}

compare() {
  local a="$1" b="$2" i result
  [[ "$a" =~ $SEMVER_RE ]] || die "'$a' is not a SemVer version"
  local a_major="${BASH_REMATCH[1]}" a_minor="${BASH_REMATCH[2]}" a_patch="${BASH_REMATCH[3]}" a_pre="${BASH_REMATCH[5]}"
  [[ "$b" =~ $SEMVER_RE ]] || die "'$b' is not a SemVer version"
  local b_major="${BASH_REMATCH[1]}" b_minor="${BASH_REMATCH[2]}" b_patch="${BASH_REMATCH[3]}" b_pre="${BASH_REMATCH[5]}"

  local -a a_core=("$a_major" "$a_minor" "$a_patch") b_core=("$b_major" "$b_minor" "$b_patch")
  for i in 0 1 2; do
    if (( 10#${a_core[$i]} < 10#${b_core[$i]} )); then echo -1; return; fi
    if (( 10#${a_core[$i]} > 10#${b_core[$i]} )); then echo 1; return; fi
  done

  # A release ranks above every pre-release of the same core.
  if [[ -z "$a_pre" && -z "$b_pre" ]]; then echo 0; return; fi
  if [[ -z "$a_pre" ]]; then echo 1; return; fi
  if [[ -z "$b_pre" ]]; then echo -1; return; fi

  local -a a_ids b_ids
  IFS='.' read -r -a a_ids <<<"$a_pre"
  IFS='.' read -r -a b_ids <<<"$b_pre"
  for ((i = 0; i < ${#a_ids[@]} && i < ${#b_ids[@]}; i++)); do
    result="$(compare_identifiers "${a_ids[$i]}" "${b_ids[$i]}")"
    if [[ "$result" != 0 ]]; then echo "$result"; return; fi
  done
  # Every shared identifier is equal: the longer pre-release ranks higher.
  if (( ${#a_ids[@]} < ${#b_ids[@]} )); then echo -1; elif (( ${#a_ids[@]} > ${#b_ids[@]} )); then echo 1; else echo 0; fi
}

case "${1:-}" in
  compare)
    [[ $# -eq 3 ]] || die "usage: $0 compare <a> <b>"
    compare "$2" "$3"
    ;;
  valid)
    [[ $# -eq 2 ]] || die "usage: $0 valid <version>"
    [[ "$2" =~ $SEMVER_RE ]]
    ;;
  *)
    die "usage: $0 compare <a> <b> | valid <version>"
    ;;
esac
