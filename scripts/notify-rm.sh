#!/usr/bin/env bash
# Declare one built version to the release managers, staging and prod:
# POST /api/v1/versions, source chart-release (existence and provenance, never
# a judgment). The same record goes to every release manager whose URL is set.
#
# Environment:
#   COMPONENT, VERSION                   required
#   RM_STAGING_URL, RM_STAGING_TOKEN     staging release manager and its ingest
#   RM_PROD_URL, RM_PROD_TOKEN           token, and the same for prod; a URL
#                                        unset or empty skips that release
#                                        manager with a warning;
#                                        https:// only (http:// for 127.0.0.1
#                                        and localhost): another URL is a
#                                        failed declaration
#   REPOSITORY, DIGEST, KIND (dev, ga, prerelease), COMMIT, BRANCH, RUN_URL,
#   RELEASE_URL, RELEASED_AT (YYYY-MM-DD), NOTE_TITLE, NOTE_DESCRIPTION,
#   META (extra key=value lines)         optional
#   DECLARATION_FILE                     optional path of the release
#                                        declaration (JSON object, ADR-0020
#                                        section 3), sent as the record field
#                                        release_declaration; a file missing
#                                        or not a JSON object is a failed
#                                        declaration (nothing is POSTed)
#   MANIFEST_FILE                        optional path of the release
#                                        manifest (JSON object, ADR-0020
#                                        section 2), sent as the record field
#                                        manifest; same rules as
#                                        DECLARATION_FILE
#   RM_STAGING_AUDIENCE,                 optional OIDC mode: when the token of
#   RM_PROD_AUDIENCE                     a release manager is empty and its
#                                        audience is set, a GitHub Actions OIDC
#                                        token for that audience is requested
#                                        (ACTIONS_ID_TOKEN_REQUEST_URL and
#                                        ACTIONS_ID_TOKEN_REQUEST_TOKEN, present
#                                        only when the job has permissions:
#                                        id-token: write) and sent as the Bearer.
#                                        A token that is set wins. The OIDC token
#                                        is masked at once and never printed
#   REQUIRED=true                        a failed declaration fails the step;
#                                        otherwise it only warns, so a release
#                                        manager outage never breaks a build
set -euo pipefail
export LC_ALL=C
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

: "${COMPONENT:?COMPONENT is required}"
: "${VERSION:?VERSION is required}"

extra_meta='{}'
while IFS= read -r line; do
  [[ -z ${line//[[:space:]]/} ]] && continue
  [[ $line == *=* ]] || die "META line '$line' is not key=value"
  extra_meta=$(jq -c --arg k "${line%%=*}" --arg v "${line#*=}" '. + {($k): $v}' <<<"$extra_meta")
done <<<"${META:-}"

# The payload and the response live in files: a release declaration can be
# larger than one command line argument may be (128 KB on Linux).
payload=$(mktemp)
response=$(mktemp)
oidc_response=$(mktemp)
curl_error=$(mktemp)
trap 'rm -f "$payload" "$response" "$oidc_response" "$curl_error"' EXIT

# The release declaration and the manifest travel as objects: jq reads the
# files itself, their content is never interpolated nor passed as an argument.
# A bad file is reported after the summary header below.
document_error=""

# object_file <label> <path>: sets object_source, the file to slurp (/dev/null
# when none), and document_error to the first bad file, when the path is not
# a JSON object.
object_file() {
  local label=$1 path=$2 jq_error
  object_source=/dev/null
  if [[ -z $path ]]; then
    return
  elif [[ ! -f $path ]]; then
    document_error=${document_error:-"$label file $path does not exist"}
  elif ! jq_error=$(jq -se 'if length == 1 and (.[0] | type) == "object" then true else error("not a JSON object") end' "$path" 2>&1 >/dev/null); then
    document_error=${document_error:-"$label file $path is not a JSON object (${jq_error%%$'\n'*})"}
  else
    object_source=$path
  fi
}
object_file "release declaration" "${DECLARATION_FILE:-}"
declaration_source=$object_source
object_file "release manifest" "${MANIFEST_FILE:-}"
manifest_source=$object_source

jq -nc \
  --arg component "$COMPONENT" \
  --arg version "$VERSION" \
  --arg repository "${REPOSITORY:-}" \
  --arg digest "${DIGEST:-}" \
  --arg release_url "${RELEASE_URL:-}" \
  --arg released_at "${RELEASED_AT:-}" \
  --arg title "${NOTE_TITLE:-}" \
  --arg description "${NOTE_DESCRIPTION:-}" \
  --arg kind "${KIND:-dev}" \
  --arg commit "${COMMIT:-}" \
  --arg branch "${BRANCH:-}" \
  --arg run "${RUN_URL:-}" \
  --argjson extra "$extra_meta" \
  --slurpfile declaration "$declaration_source" \
  --slurpfile manifest "$manifest_source" \
  'def opt: if . == "" then null else . end;
  [{
    component_id: $component,
    component_version: $version,
    source: "chart-release",
    app_version: $version,
    repository: ($repository | opt),
    digest: ($digest | opt),
    release_url: ($release_url | opt),
    released_at: ($released_at | opt),
    release_note: ({title: ($title | opt), description: ($description | opt)}
                   | with_entries(select(.value != null))
                   | if . == {} then null else . end),
    release_declaration: $declaration[0],
    manifest: $manifest[0],
    meta: (({build: $kind, commit: $commit, branch: $branch, run: $run}
            | with_entries(select(.value != ""))) + $extra)
  } | with_entries(select(.value != null))]' >"$payload"

failed=()
allowed_url_re='^(https://|http://(127\.0\.0\.1|localhost)(:[0-9]+)?(/|$))'

# request_oidc_token <name> <audience>: sets oidc_value to a GitHub Actions OIDC
# token for the audience; returns 1 (a warning, like any notify-rm error) when
# the job cannot get one. Not run in a subshell: the ::add-mask:: command must
# reach the log before anything else could print the token. The request token
# goes to curl on stdin, like the ingest token; no response body is ever shown.
request_oidc_token() {
  local name=$1 audience=$2 encoded code sep='&'
  oidc_value=""
  if [[ -z ${ACTIONS_ID_TOKEN_REQUEST_URL:-} || -z ${ACTIONS_ID_TOKEN_REQUEST_TOKEN:-} ]]; then
    echo "::warning::release manager $name: no OIDC token, the job lacks permissions: id-token: write (job level), $COMPONENT $VERSION is not declared there"
    summary "- release manager $name: not declared, no id-token permission"
    return 1
  fi
  if [[ ! $ACTIONS_ID_TOKEN_REQUEST_URL =~ $allowed_url_re || $ACTIONS_ID_TOKEN_REQUEST_TOKEN == *[$'\r\n"\\']* ]]; then
    echo "::warning::release manager $name: the OIDC token endpoint is not usable, $COMPONENT $VERSION is not declared there"
    summary "- release manager $name: not declared, OIDC endpoint not usable"
    return 1
  fi
  [[ $ACTIONS_ID_TOKEN_REQUEST_URL == *\?* ]] || sep='?'
  encoded=$(jq -rn --arg a "$audience" '$a | @uri')
  code=$(printf 'header = "Authorization: Bearer %s"\n' "$ACTIONS_ID_TOKEN_REQUEST_TOKEN" |
    curl --config - -sS --retry 2 --max-time 30 -o "$oidc_response" -w '%{http_code}' \
      "${ACTIONS_ID_TOKEN_REQUEST_URL}${sep}audience=${encoded}") || code=000
  oidc_value=$(jq -r '.value // empty' "$oidc_response" 2>/dev/null || true)
  # A JWT only: the value goes into a workflow command and a header.
  if [[ $code != 2?? || ! $oidc_value =~ ^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*$ ]]; then
    oidc_value=""
    echo "::warning::release manager $name: no OIDC token for the $name audience (HTTP $code), $COMPONENT $VERSION is not declared there"
    summary "- release manager $name: not declared, no OIDC token"
    return 1
  fi
  echo "::add-mask::$oidc_value"
}

# Declare to one release manager; returns 1 when that declaration failed.
declare_to() {
  local name=$1 var=$2 url=$3 token=$4 audience=${5:-} code hint stop curl_status host
  if [[ -z $url ]]; then
    echo "::warning::release manager $name: $var is not set or empty, $COMPONENT $VERSION is not declared there"
    summary "- release manager $name: skipped, $var not set"
    return 0
  fi
  # A line break in a variable would let it write workflow commands into the log.
  if [[ $url == *[[:cntrl:]]* ]]; then
    echo "::warning::release manager $name (rm-$name): the URL holds a control character, $COMPONENT $VERSION is not declared there"
    summary "- release manager $name: not declared, invalid URL"
    return 1
  fi
  # The job log of a public component is public: from here on the URL and its
  # host are masked, in case a failure body, a proxy page or a tool echoes them.
  echo "::add-mask::${url%/}"
  host=${url#*://}
  host=${host%%[/?#]*}
  host=${host##*@}
  host=${host%%:*}
  [[ -z $host ]] || echo "::add-mask::$host"
  # The ingest token never travels in clear text: https only, but for a
  # loopback release manager (tests).
  if [[ ! $url =~ $allowed_url_re ]]; then
    echo "::warning::release manager $name (rm-$name): not an https:// URL, $COMPONENT $VERSION is not declared there"
    summary "- release manager $name: not declared, not an https:// URL"
    return 1
  fi
  if [[ -z $token && -n ${audience//[[:space:]]/} ]]; then
    request_oidc_token "$name" "$audience" || return 1
    token=$oidc_value
  fi
  if [[ -z $token ]]; then
    echo "::warning::release manager $name (rm-$name): no ingest token, $COMPONENT $VERSION is not declared there"
    summary "- release manager $name: not declared, no token"
    return 1
  fi
  if [[ $token == *[$'\r\n']* ]]; then
    echo "::warning::release manager $name (rm-$name): the ingest token holds a line break, $COMPONENT $VERSION is not declared there"
    summary "- release manager $name: not declared, invalid token"
    return 1
  fi
  # The token goes to curl as a config file on stdin, written by the printf
  # builtin: never on a command line, where ps shows it. Quoted config
  # strings take backslash escapes, hence \ and " escaped.
  token=${token//\\/\\\\}
  token=${token//\"/\\\"}
  # No -L: an SSO-fronted host answers a machine with a 302 to a login page.
  # curl names the host in its errors: its stderr stays out of the job log, which
  # is public for a public component; only its exit status is shown.
  curl_status=0
  code=$(printf 'header = "Authorization: Bearer %s"\n' "$token" |
    curl --config - -sS --retry 3 --retry-connrefused --max-time 60 -o "$response" -w '%{http_code}' \
      -X POST "${url%/}/api/v1/versions" \
      -H 'Content-Type: application/json' \
      --data "@$payload" 2>"$curl_error") || { curl_status=$?; code=000; }
  echo "release manager $name: HTTP $code"
  [[ $curl_status == 0 ]] || echo "release manager $name: curl exit status $curl_status"
  if [[ $code != 2?? ]]; then
    # The body only on failure, short, and never read as workflow commands:
    # the job log of a public component is public.
    stop=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')
    echo "::stop-commands::$stop"
    head -c 500 "$response" || true
    echo
    echo "::$stop::"
    hint=""
    [[ $code == 3?? ]] && hint=" (a 3xx means an interactive SSO in front of the API)"
    [[ $code == 000 ]] && hint=" (unreachable)"
    echo "::warning::release manager $name (rm-$name) answered $code$hint: $COMPONENT $VERSION not declared there"
    summary "- release manager $name: not declared, HTTP $code$hint"
    return 1
  fi
  echo "::notice::$COMPONENT $VERSION declared to the $name release manager"
  summary "- release manager $name: declared"
}

summary "### Release managers: $COMPONENT $VERSION"
if [[ -n $document_error ]]; then
  echo "::warning::$document_error: $COMPONENT $VERSION is not declared"
  summary "- not declared: $document_error"
  [[ ${REQUIRED:-false} != true ]] || die "declaration failed: $document_error"
  exit 0
fi
declare_to staging RM_STAGING_URL "${RM_STAGING_URL:-}" "${RM_STAGING_TOKEN:-}" "${RM_STAGING_AUDIENCE:-}" || failed+=(staging)
declare_to prod RM_PROD_URL "${RM_PROD_URL:-}" "${RM_PROD_TOKEN:-}" "${RM_PROD_AUDIENCE:-}" || failed+=(prod)

if ((${#failed[@]})) && [[ ${REQUIRED:-false} == true ]]; then
  die "declaration failed on: ${failed[*]}"
fi
