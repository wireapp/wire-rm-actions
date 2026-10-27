#!/usr/bin/env bash
# Log in to a Quay registry with the GitHub Actions OIDC token of the job,
# through a federated robot account (Quay 3.16 robot identity federation):
# the token of the run is exchanged at /oauth2/federation/robot/token for a
# robot token valid one hour. Nothing is stored anywhere: no secret in the
# repository, nothing to rotate.
#
# Environment:
#   ROBOT                 required, <organization>+<name> (Quay's naming rule:
#                         lowercase, digits, single . _ - inside), a robot account of an
#                         organization whose federation lists the GitHub issuer
#                         and the subject of this job
#   REGISTRY              registry host, default quay.io
#   AUDIENCE              OIDC audience the federation accepts, default quay
#   DOCKER_LOGIN=true     also run docker login with the robot token (default)
#   FEDERATION_URL        exchange endpoint, default
#                         https://<REGISTRY>/oauth2/federation/robot/token
#                         (tests only: http:// is accepted for 127.0.0.1 and
#                         localhost)
#   ACTIONS_ID_TOKEN_REQUEST_URL, ACTIONS_ID_TOKEN_REQUEST_TOKEN
#                         set by the runner when the job has permissions:
#                         id-token: write
#
# A failure is an error: a build that cannot log in must not go on. Both tokens
# are masked as soon as they exist and never printed; they reach curl and
# docker on stdin only, never on a command line. Prints token= to
# $GITHUB_OUTPUT when set.
set -euo pipefail
export LC_ALL=C
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

: "${ROBOT:?ROBOT is required}"
registry=${REGISTRY:-quay.io}
audience=${AUDIENCE:-quay}
docker_login=${DOCKER_LOGIN:-true}
federation_url=${FEDERATION_URL:-https://${registry}/oauth2/federation/robot/token}

allowed_url_re='^(https://|http://(127\.0\.0\.1|localhost)(:[0-9]+)?(/|$))'
# Quay's own rule for a namespace and a robot short name (util/validation.py,
# VALID_USERNAME_REGEX): lowercase letters and digits, single . _ - between them.
# Nothing else may reach the curl config line below.
name_re='[a-z0-9]+([._-][a-z0-9]+)*'
[[ $ROBOT =~ ^${name_re}\+${name_re}$ ]] || die "ROBOT must be <organization>+<name>, not '$ROBOT'"
[[ $registry =~ ^[A-Za-z0-9.-]+(:[0-9]+)?$ ]] || die "REGISTRY must be a host, not '$registry'"
[[ $audience =~ ^[A-Za-z0-9._:/-]+$ ]] || die "AUDIENCE must be a plain word, not '$audience'"
[[ $federation_url =~ $allowed_url_re ]] || die "FEDERATION_URL must be https://"
if [[ -z ${ACTIONS_ID_TOKEN_REQUEST_URL:-} || -z ${ACTIONS_ID_TOKEN_REQUEST_TOKEN:-} ]]; then
  die "no OIDC token endpoint: the job needs permissions: id-token: write (job level)"
fi
if [[ ! $ACTIONS_ID_TOKEN_REQUEST_URL =~ $allowed_url_re || $ACTIONS_ID_TOKEN_REQUEST_TOKEN == *[$'\r\n"\\']* ]]; then
  die "the OIDC token endpoint is not usable"
fi

response=$(mktemp)
trap 'rm -f "$response"' EXIT

# 1. The OIDC token of the job, for the audience the federation accepts. The
#    request token goes to curl as a config file on stdin.
sep='&'
[[ $ACTIONS_ID_TOKEN_REQUEST_URL == *\?* ]] || sep='?'
encoded=$(jq -rn --arg a "$audience" '$a | @uri')
code=$(printf 'header = "Authorization: Bearer %s"\n' "$ACTIONS_ID_TOKEN_REQUEST_TOKEN" |
  curl --config - -sS --retry 2 --max-time 30 -o "$response" -w '%{http_code}' \
    "${ACTIONS_ID_TOKEN_REQUEST_URL}${sep}audience=${encoded}") || code=000
oidc=$(jq -r '.value // empty' "$response" 2>/dev/null || true)
# A JWT only: the value goes into a workflow command and a header.
if [[ $code != 2?? || ! $oidc =~ ^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*$ ]]; then
  die "no OIDC token for audience $audience (HTTP $code)"
fi
echo "::add-mask::$oidc"

# 2. The exchange: basic auth robot:oidc-token, on stdin.
: >"$response"
code=$(printf 'user = "%s:%s"\n' "$ROBOT" "$oidc" |
  curl --config - -sS --retry 2 --retry-connrefused --max-time 30 -o "$response" -w '%{http_code}' \
    "$federation_url") || code=000
token=$(jq -r '.token // empty' "$response" 2>/dev/null || true)
if [[ $code != 2?? || -z $token || $token == *[$'\r\n']* ]]; then
  # A short, filtered excerpt of a JSON error only; never the body as is.
  reason=$(jq -r '(.error_description // .error // .message // "") | tostring | .[0:200]' "$response" 2>/dev/null |
    tr -cd 'A-Za-z0-9 ._,()/-' || true)
  die "$registry refused the federation exchange for $ROBOT (HTTP $code${reason:+, $reason}): check the robot federation (issuer, subject of this job, audience $audience)"
fi
echo "::add-mask::$token"

# 3. docker login, the token on stdin.
if [[ $docker_login == true ]]; then
  printf '%s' "$token" | docker login "$registry" --username "$ROBOT" --password-stdin >/dev/null
  echo "Logged in to $registry as $ROBOT with the OIDC token of this run (robot token valid one hour)."
else
  echo "Robot token for $registry as $ROBOT obtained with the OIDC token of this run (valid one hour)."
fi

if [[ -n ${GITHUB_OUTPUT:-} ]]; then
  echo "token=$token" >>"$GITHUB_OUTPUT"
fi
