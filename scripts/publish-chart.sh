#!/usr/bin/env bash
# Push a Helm chart to the ADR-0012 layout oci://<REGISTRY>/wire/charts/<CHANNEL>/<name>,
# in one of two modes:
#   - package (CHART_PATH): package the chart directory at VERSION (chart version
#     == appVersion, ADR-0018; APP_VERSION overrides the appVersion, for the
#     extra charts that repackage an upstream release) and push it, optionally
#     with a Quay expiration;
#   - chart file (CHART_FILE): push an already packaged .tgz as is, the exact
#     asset of a draft release, without repackaging and never with an expiration.
#     Its appVersion must be its version, or APP_VERSION when given.
# A version already in the registry is never overwritten: in package mode its
# digest is read back; in chart-file mode the same content (the pulled .tgz has
# the sha256 of the given one) is a no-op and another content a hard failure.
# So a rerun of the same commit or the same candidate is safe. A presence check
# that fails for another reason than an absent version stops the script.
# With ATTEMPTS > 1 (chart file mode only) a failed push is tried again: Quay
# has answered 500 on a manifest PUT that had committed, so the presence check
# runs again before every push and a chart that landed meanwhile is a no-op
# (or a failure when its content differs), never a second push. Only a failed
# push is tried again: a presence check that cannot tell stops at once.
#
# Environment: CHART_PATH or CHART_FILE (one of them); VERSION (required with
# CHART_PATH, checked against the package with CHART_FILE); CHART_NAME (default:
# the Chart.yaml name), REGISTRY (default quay.io), CHANNEL (default dev),
# ATTEMPTS (default 1: no retry; CHART_FILE only), RETRY_DELAY (seconds between
# attempts, default 10),
# APP_VERSION (set by publish-extra-chart only: the appVersion of the package
# instead of VERSION; with CHART_FILE, the appVersion the package must have),
# EXPIRES_AFTER (dev channel, package mode only, e.g. 90d: Quay deletes the tag
# after that delay; the pushed manifest gets the quay.expires-after annotation,
# which helm push cannot set, so oras rewrites it: needs oras and jq on PATH).
# The registry login is done beforehand (helm registry login).
# Prints repository=, digest= and status= (pushed | present), and appends them
# to $GITHUB_OUTPUT when set.
set -euo pipefail
export LC_ALL=C
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

chart_path=${CHART_PATH:-}
chart_file=${CHART_FILE:-}
version=${VERSION:-}
registry=${REGISTRY:-quay.io}
channel=${CHANNEL:-dev}
expires_after=${EXPIRES_AFTER:-}
app_version=${APP_VERSION:-}
attempts=${ATTEMPTS:-1}
retry_delay=${RETRY_DELAY:-10}

[[ $attempts =~ ^[1-9][0-9]*$ ]] || die "ATTEMPTS must be a positive number, not '$attempts'"
[[ $retry_delay =~ ^[0-9]+$ ]] || die "RETRY_DELAY must be a number of seconds, not '$retry_delay'"

if [[ -n $chart_path && -n $chart_file ]]; then
  die "CHART_PATH and CHART_FILE are exclusive: a chart directory to package, or a packaged chart to push as is"
fi
[[ -n $chart_path || -n $chart_file ]] || die "CHART_PATH or CHART_FILE is required"
if (( attempts > 1 )) && [[ -z $chart_file ]]; then
  die "ATTEMPTS is for CHART_FILE only: a chart directory is packaged and pushed once"
fi
if [[ -n $app_version ]]; then
  [[ $app_version =~ ^[0-9A-Za-z][0-9A-Za-z.+_-]*$ ]] \
    || die "APP_VERSION must be a version string (letters, digits and . + _ -), not '$app_version'"
fi
if [[ -n $expires_after ]]; then
  [[ -z $chart_file ]] || die "EXPIRES_AFTER is refused with CHART_FILE: a published chart never expires"
  [[ $expires_after =~ ^[1-9][0-9]*[hdw]$ ]] \
    || die "EXPIRES_AFTER must be a number of hours, days or weeks (e.g. 90d), not '$expires_after'"
  [[ $channel == dev ]] || die "EXPIRES_AFTER is for the dev channel only: a $channel chart never expires"
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
# helm pull does not create its destination: without it every pull fails, which
# reads as "not published" and the version would be pushed over.
mkdir "$work/existing"

chart_field() { # <chart dir or .tgz> <field>
  helm show chart "$1" | sed -n "s/^$2: *//p" | head -n1 | sed "s/^[\"']//; s/[\"']\$//"
}

if [[ -n $chart_file ]]; then
  [[ -f $chart_file ]] || die "CHART_FILE '$chart_file' not found"
  name=$(chart_field "$chart_file" name)
  [[ -n $name ]] || die "cannot read the chart name from $chart_file"
  file_version=$(chart_field "$chart_file" version)
  [[ -n $file_version ]] || die "cannot read the chart version from $chart_file"
  file_app_version=$(chart_field "$chart_file" appVersion)
  if [[ -n $app_version ]]; then
    [[ $file_app_version == "$app_version" ]] \
      || die "$chart_file has appVersion '$file_app_version', expected '$app_version'"
  else
    [[ $file_app_version == "$file_version" ]] \
      || die "$chart_file has appVersion '$file_app_version', expected the chart version '$file_version' (ADR-0018)"
  fi
  if [[ -n $version && $version != "$file_version" ]]; then
    die "$chart_file is version '$file_version', expected '$version'"
  fi
  version=$file_version
  if [[ -n ${CHART_NAME:-} && ${CHART_NAME} != "$name" ]]; then
    die "$chart_file is the chart '$name', expected '$CHART_NAME'"
  fi
  [[ $(basename "$chart_file") == "${name}-${version}.tgz" ]] \
    || die "$chart_file should be named ${name}-${version}.tgz"
else
  [[ -n $version ]] || die "VERSION is required"
  name=${CHART_NAME:-$(chart_field "$chart_path" name)}
  [[ -n $name ]] || die "cannot read the chart name from $chart_path/Chart.yaml"
fi

base="oci://${registry}/wire/charts/${channel}"
repository="${base}/${name}"

digest_of() {
  sed -n 's/^Digest: *//p' "$1" | tail -n1
}

# Only the registry's answer to the manifest request ("FetchReference" in helm's
# error) that the version is not there makes it absent: helm's "not found", the
# OCI error messages, or a 401, 403 or 404 status. Any other failure of helm
# pull (a local error such as a file it cannot write, the network, a 5xx) stops
# here: taking it for absent would push over a published version. So does a
# 403 or 404 on a blob ("Fetch"): the manifest is there, and Quay serves the
# blobs from another host (a CDN) than the one the push goes to. A missing
# repository answers 401/403, and so does an invalid robot: in both cases the
# push fails the same way and overwrites nothing.
readonly absent_re='"FetchReference" on source: .*(: not found|manifest unknown|name unknown|response status code 40[134])'

status=pushed
digest=
attempt=1
while true; do
  if helm pull "$repository" --version "$version" -d "$work/existing" >"$work/pull.log" 2>&1; then
    if [[ -n $chart_file ]]; then
      existing="$work/existing/${name}-${version}.tgz"
      [[ -f $existing ]] || die "helm pull did not save $existing"
      [[ $(sha256_of "$existing") == "$(sha256_of "$chart_file")" ]] \
        || die "$repository:$version is already published with another content; a version is never overwritten"
      echo "::notice::$repository:$version already published with the same chart, nothing to push"
    else
      echo "::notice::$repository:$version already published, not overwritten"
    fi
    digest=$(digest_of "$work/pull.log")
    status=present
    break
  elif ! absent=$(grep -iE -m1 "$absent_re" "$work/pull.log"); then
    cat "$work/pull.log" >&2
    die "cannot tell whether $repository:$version is published: helm pull failed, and not because the version is absent"
  elif [[ -n $chart_file ]]; then
    echo "$repository:$version is not published yet: ${absent#Error: }"
    if helm push "$chart_file" "$base" 2>&1 | tee "$work/push.log"; then
      digest=$(digest_of "$work/push.log")
      break
    fi
    (( attempt < attempts )) || die "helm push of $chart_file to $base failed after $attempt attempt(s)"
    echo "::warning::helm push to $base failed (attempt $attempt/$attempts), trying again in ${retry_delay}s"
    sleep "$retry_delay"
    attempt=$((attempt + 1))
  else
    echo "$repository:$version is not published yet: ${absent#Error: }"
    # An apiVersion v1 chart declares its dependencies in requirements.yaml.
    if grep -q '^dependencies:' "$chart_path/Chart.yaml" || [[ -f $chart_path/requirements.yaml ]]; then
      # Only when one is missing: a caller that already ran helm dependency
      # update has them all, and build would need their http(s) repositories
      # added with helm repo add. helm package refuses a missing dependency.
      dependencies=$(helm dependency list "$chart_path") || die "cannot list the dependencies of $chart_path"
      if awk 'NR > 1 && NF && $NF != "ok" && $NF != "unpacked" {missing = 1} END {exit !missing}' <<<"$dependencies"; then
        helm dependency build "$chart_path"
      fi
    fi
    helm package "$chart_path" --version "$version" --app-version "${app_version:-$version}" -d "$work"
    helm push "$work/${name}-${version}.tgz" "$base" 2>&1 | tee "$work/push.log"
    digest=$(digest_of "$work/push.log")
    if [[ -n $expires_after && $digest == sha256:* ]]; then
      # Same layers and config, one more annotation: the tag moves to the new
      # manifest, whose digest is the sha256 of the exact bytes pushed.
      target="${repository#oci://}:${version}"
      registry_config=$(helm env HELM_REGISTRY_CONFIG)
      oras manifest fetch --registry-config "$registry_config" "$target" >"$work/manifest.json"
      jq -c --arg after "$expires_after" \
        '.annotations = ((.annotations // {}) + {"quay.expires-after": $after})' \
        "$work/manifest.json" >"$work/annotated.json"
      media_type=$(jq -r '.mediaType // "application/vnd.oci.image.manifest.v1+json"' "$work/annotated.json")
      oras manifest push --registry-config "$registry_config" --media-type "$media_type" \
        "$target" "$work/annotated.json"
      digest="sha256:$(sha256_of "$work/annotated.json")"
      echo "$target expires after $expires_after ($digest)"
    fi
    break
  fi
done

[[ $digest == sha256:* ]] || die "no digest for $repository:$version"

emit repository "$repository"
emit digest "$digest"
emit status "$status"
