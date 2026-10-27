#!/usr/bin/env bash
# Read a component's compatibility file (ADR-0020 section 3), check it, and
# write it as JSON in the two shapes in use during the transition:
#
#   compatibility.json           the ADR-0020 document (Backstage field names:
#                                providesApis, consumesApis, dependsOn,
#                                includes), what the v1alpha2 manifest carries;
#   manifest-compatibility.json  the provides / requires / includes object the
#                                release manager reads today (manifest
#                                wire.component-release-manifest/v1alpha1).
#
# The file is publication/compatibility.yaml: the four lists above, all
# required ([] when empty), no other key. The former root compatibility.yaml
# (provides, requires) is refused with the move to make.
#
# Mapping ADR-0020 -> manifest (the inverse of what the release manager will
# read once it knows the ADR-0020 names; drop it then):
#   providesApis[{api, versions}]          -> provides[{interface, supported, deprecated, development}]
#   consumesApis[{api, versions, class}]   -> requires[{interface, range, class, reason}]
#   dependsOn[{resource|component|platform, range, class}]
#                                          -> requires[{capability|component|platform, range, class, reason}]
# A list of API versions becomes "<min>-<max>" when contiguous, else the
# versions joined with ","; class `alternative` becomes `optional`.
#
# Environment:
#   FILE        the compatibility file; default publication/compatibility.yaml
#   OUTPUT_DIR  where the JSON files are written; default a new temporary
#               directory
#
# Needs jq and yq (mikefarah, v4; on the GitHub runners).
#
# Prints and appends to $GITHUB_OUTPUT: file, compatibility (path),
# manifest-compatibility (path). Every error is printed as a
# ::error:: line; any error fails with exit 1.
set -euo pipefail
export LC_ALL=C
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

command -v yq >/dev/null || die "yq (mikefarah, v4) is required"
yq --version 2>&1 | grep -q 'mikefarah' || die "yq must be mikefarah's yq v4, not $(yq --version 2>&1 | head -n1)"

file=${FILE:-}
if [[ -z $file ]]; then
  file=publication/compatibility.yaml
  if [[ ! -f $file && -f compatibility.yaml ]]; then
    die "no compatibility file at $file: the root compatibility.yaml (provides, requires) is the former layout, move it to $file with providesApis, consumesApis, dependsOn and includes (ADR-0020 section 3)"
  fi
  [[ -f $file ]] || die "no compatibility file: $file (ADR-0020 section 3)"
fi
[[ -f $file ]] || die "$file: compatibility file does not exist"

out=${OUTPUT_DIR:-}
if [[ -z $out ]]; then
  out=$(mktemp -d)
fi
mkdir -p "$out"

json=$(yq -o=json -I=0 '.' "$file" 2>/dev/null) || die "$file: not valid YAML"
[[ -n $json && $json != null ]] || die "$file: empty document"

format=$(jq -r '
  if type != "object" then "invalid"
  elif has("providesApis") or has("consumesApis") or has("dependsOn") then "adr-0020"
  elif has("provides") or has("requires") then "former"
  else "unknown" end' <<<"$json")

case $format in
invalid) die "$file: the document is not a mapping" ;;
former) die "$file: the former format (provides, requires) is not read any more; write providesApis, consumesApis, dependsOn and includes (ADR-0020 section 3)" ;;
unknown) die "$file: not the ADR-0020 format (providesApis, consumesApis, dependsOn, includes)" ;;
esac

# One line per error, in document order. The $names are jq variables.
# shellcheck disable=SC2016
check_adr='
def str: type == "string" and length > 0;
def ints: type == "array" and all(.[]; type == "number" and . == floor and . >= 0);
def semvers: type == "array" and length > 0 and all(.[]; str);
def versions_ok: (ints and length > 0) or semvers or str;
def class_and_reason($w):
  (if has("class") and ((.class | IN("mandatory", "optional", "alternative")) | not)
   then "\($w).class must be mandatory, optional or alternative" else empty end),
  (if (.class | IN("optional", "alternative")) and ((.reason // "") | str | not)
   then "\($w) is \(.class) and needs a reason" else empty end);
def entries($name):
  if (.[$name] | type) != "array" then "\($name) must be a list ([] when empty)"
  else .[$name] | to_entries[] | select(.value | type != "object") | "\($name)[\(.key)] is not a mapping"
  end;
def objects($name): .[$name] // [] | if type == "array" then to_entries[] | select(.value | type == "object") else empty end;
(keys - ["providesApis", "consumesApis", "dependsOn", "includes"] | .[] | "unknown key \(.)"),
entries("providesApis"),
(objects("providesApis") | .key as $i | .value
  | (if (.api | str | not) then "providesApis[\($i)].api is required" else empty end),
    (if (.versions | type) == "object" then
       (if (.versions | keys - ["supported", "deprecated", "development"] | length) > 0
        then "providesApis[\($i)].versions only holds supported, deprecated and development" else empty end),
       (if (.versions.supported | ints | not) then "providesApis[\($i)].versions.supported must be a list of API versions" else empty end),
       (["deprecated", "development"][] as $k | select(.versions | has($k)) | select(.versions[$k] | ints | not)
        | "providesApis[\($i)].versions.\($k) must be a list of API versions")
     elif (.versions | semvers) then empty
     else "providesApis[\($i)].versions must be {supported, deprecated, development} or a list of versions" end)),
entries("consumesApis"),
(objects("consumesApis") | .key as $i | .value
  | (if (.api | str | not) then "consumesApis[\($i)].api is required" else empty end),
    (if (.versions | versions_ok | not) then "consumesApis[\($i)].versions must be a list of API versions or a range" else empty end),
    class_and_reason("consumesApis[\($i)]")),
entries("dependsOn"),
(objects("dependsOn") | .key as $i | .value
  | (if ([has("resource", "component", "platform")] | map(select(.)) | length) != 1
     then "dependsOn[\($i)] must name exactly one of resource, component or platform" else empty end),
    (if (.range | str | not) then "dependsOn[\($i)].range is required" else empty end),
    class_and_reason("dependsOn[\($i)]")),
entries("includes"),
(objects("includes") | .key as $i | .value
  | (if (.component | str | not) then "includes[\($i)].component is required" else empty end),
    (if ([has("version", "range")] | map(select(.)) | length) != 1 then "includes[\($i)] needs exactly one of version or range" else empty end),
    (if has("class") then "includes[\($i)] is unconditional and has no class" else empty end),
    (if (.reason // "") | str | not then "includes[\($i)].reason is required" else empty end))
'

# shellcheck disable=SC2016
to_manifest='
def range_of:
  if type == "array" then
    if all(.[]; type == "number") then
      (sort) as $v
      | if ($v | length) == 1 then "\($v[0])"
        elif ($v | length) > 0 and ($v[-1] - $v[0] + 1) == ($v | length) then "\($v[0])-\($v[-1])"
        else $v | map(tostring) | join(",") end
    else map(tostring) | join(",") end
  else tostring end;
def drop_empty: with_entries(select(.value != null and .value != ""));
def manifest_class: if . == "alternative" then "optional" else . end;
{
  provides: [.providesApis[] | {
    interface: .api,
    supported: (if (.versions | type) == "object" then .versions.supported else .versions end | range_of),
    deprecated: (if (.versions | type) == "object" then .versions.deprecated // [] | range_of else null end),
    development: (if (.versions | type) == "object" then .versions.development // [] | range_of else null end)
  } | drop_empty],
  requires: (
    [.consumesApis[] | {interface: .api, range: (.versions | range_of), class: (.class // null | manifest_class), reason} | drop_empty]
    + [.dependsOn[] | {capability: .resource, component, platform, range: (.range | tostring),
                        class: (.class // null | manifest_class), reason} | drop_empty]
  ),
  includes: .includes
}
'

errors=$(jq -r "$check_adr" <<<"$json")
if [[ -n $errors ]]; then
  while IFS= read -r line; do
    echo "::error::$file: $line" >&2
  done <<<"$errors"
  die "$file: invalid compatibility file"
fi

compatibility="$out/compatibility.json"
manifest="$out/manifest-compatibility.json"
jq . <<<"$json" >"$compatibility"
jq "$to_manifest" <<<"$json" >"$manifest"
jq -r --arg f "$file" '"\($f): valid compatibility file, \(.providesApis | length) providesApis, \(.consumesApis | length) consumesApis, \(.dependsOn | length) dependsOn, \(.includes | length) includes"' <<<"$json"

emit file "$file"
emit compatibility "$compatibility"
emit manifest-compatibility "$manifest"
