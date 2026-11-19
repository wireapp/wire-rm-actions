#!/usr/bin/env bash
# Helpers shared by the action scripts. Sourced, never run:
#
#   # shellcheck source=scripts/lib.sh
#   source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
#
# The caller sets its own options (set -euo pipefail, LC_ALL=C).
#
#   here             this directory (scripts/), for sibling scripts
#   die <message>    ::error:: line on stderr, exit 1
#   warn <message>   ::warning:: line on stderr
#   annotate <level> <title> <message>
#                    titled annotation (::warning title=...::message) on stdout,
#                    the title in bold in the run's annotation list; both parts
#                    escaped as workflow commands require
#   emit <key> <value>
#                    key=value on stdout, appended to $GITHUB_OUTPUT when set
#   sha256_of <file> hex digest, with sha256sum or shasum (macOS)
#   summary <line>...
#                    lines appended to the job summary ($GITHUB_STEP_SUMMARY) when set

# shellcheck disable=SC2034 # used by the sourcing scripts
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly here

die() {
  echo "::error::$*" >&2
  exit 1
}

warn() {
  echo "::warning::$*" >&2
}

# A GitHub annotation with a title: the run's annotation list shows the title in
# bold and the message under it, so the message stays one line and the detail
# goes to the job summary. Level: notice, warning or error. Percent, CR and LF
# are escaped in both parts, colon and comma in the title too: nothing in a
# value can end the command or start another one.
annotate() {
  local level=$1 title=$2 message=$3
  title=${title//%/%25}
  title=${title//$'\r'/%0D}
  title=${title//$'\n'/%0A}
  title=${title//:/%3A}
  title=${title//,/%2C}
  message=${message//%/%25}
  message=${message//$'\r'/%0D}
  message=${message//$'\n'/%0A}
  printf '::%s title=%s::%s\n' "$level" "$title" "$message"
}

emit() {
  printf '%s=%s\n' "$1" "$2"
  if [[ -n ${GITHUB_OUTPUT:-} ]]; then
    printf '%s=%s\n' "$1" "$2" >>"$GITHUB_OUTPUT"
  fi
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

summary() {
  if [[ -n ${GITHUB_STEP_SUMMARY:-} ]]; then
    printf '%s\n' "$@" >>"$GITHUB_STEP_SUMMARY"
  fi
}
