#!/usr/bin/env bash
# Validate release declarations (ADR-0020 section 4) against the vendored
# schema schemas/wire.component-release-v1alpha2.json. Every error of a
# document is printed as a ::error:: line; the first invalid document ends
# the run with exit 1.
#
# The check runs in jq, present on every runner, so the action pulls no
# Python package at run time. jq interprets the schema itself (the single
# source of truth) for the keywords it uses: type, const, enum, required,
# properties, additionalProperties, items, pattern, minLength, maxLength.
# tests/test_release_declaration.py checks that the schema uses no other
# keyword and that jq and the jsonschema package agree on the fixtures.
#
# Usage: release-declaration.sh [file...]
#
# Environment:
#   FILE                 the document, when no file is given as argument
#   COMPONENT, VERSION   optional: must equal the document's fields
#   SCHEMA               optional: another schema file (tests)
set -euo pipefail
export LC_ALL=C
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

schemas_dir="$(cd "$here/.." && pwd)/schemas"
files=("$@")
if ((${#files[@]} == 0)); then
  : "${FILE:?FILE (or a file argument) is required}"
  files=("$FILE")
fi

# One line per error, "<json path>: <message>", in document order. The $names
# are jq variables, not shell ones.
# shellcheck disable=SC2016
validate='
def ptr: if length == 0 then "$" else "$" + (map(if type == "number" then "[\(.)]" else ".\(.)" end) | add) end;
def errors($s; $p):
  . as $v
  | (if $s | has("const") then
       if $v != $s.const then "\($p | ptr): must be \($s.const | tojson)" else empty end
     else empty end),
    (if $s | has("enum") then
       if any($s.enum[]; . == $v) then empty else "\($p | ptr): must be one of \($s.enum | tojson)" end
     else empty end),
    (if $s | has("type") then
       ($s.type | if type == "array" then . else [.] end) as $types
       | if any($types[]; . == ($v | type)) then empty
         else "\($p | ptr): must be \($types | join(" or ")), not \($v | type)" end
     else empty end),
    (if ($v | type) == "string" then
       (if ($s | has("minLength")) and ($v | length) < $s.minLength then
          "\($p | ptr): must be at least \($s.minLength) character(s) long" else empty end),
       (if ($s | has("maxLength")) and ($v | length) > $s.maxLength then
          "\($p | ptr): must be at most \($s.maxLength) character(s) long" else empty end),
       (if ($s | has("pattern")) and ($v | test($s.pattern) | not) then
          "\($p | ptr): must match \($s.pattern)" else empty end)
     else empty end),
    (if ($v | type) == "object" then
       (($s.required // [])[] as $k
        | if $v | has($k) then empty else "\($p | ptr): missing required key \($k)" end),
       (if $s.additionalProperties == false then
          ($v | keys_unsorted[]) as $k
          | if ($s.properties // {}) | has($k) then empty else "\($p | ptr): unexpected key \($k)" end
        else empty end),
       (($s.properties // {}) | to_entries[] | .key as $k | .value as $sub
        | if $v | has($k) then ($v[$k] | errors($sub; $p + [$k])) else empty end)
     else empty end),
    (if ($v | type) == "array" and ($s | has("items")) then
       ($v | to_entries[] | .key as $i | .value | errors($s.items; $p + [$i]))
     else empty end);
[errors($schema[0]; [])][]
'

# A document value on one line, control characters escaped as in JSON: a line
# break would let the document start its own workflow command (::warning::...).
oneline() {
  jq -rn --arg s "$1" '$s | tojson | .[1:-1]'
}

for file in "${files[@]}"; do
  [[ -f $file ]] || die "$file: release declaration file does not exist"
  jq -e . "$file" >/dev/null 2>&1 || die "$file: not a JSON document"
  # v1alpha2 (ADR-0020 section 4, publication/declaration.json); any other
  # schemaVersion is reported by its const.
  schema=${SCHEMA:-$schemas_dir/wire.component-release-v1alpha2.json}
  found=0
  while IFS= read -r line; do
    echo "::error::$file: $line" >&2
    found=1
  done < <(jq -r --slurpfile schema "$schema" "$validate" "$file")
  component=$(jq -r '.component // "" | tostring' "$file")
  version=$(jq -r '.version // "" | tostring' "$file")
  if [[ -n ${COMPONENT:-} && $COMPONENT != "$component" ]]; then
    echo "::error::$file: component is '$(oneline "$component")', expected '$(oneline "$COMPONENT")'" >&2
    found=1
  fi
  if [[ -n ${VERSION:-} && $VERSION != "$version" ]]; then
    echo "::error::$file: version is '$(oneline "$version")', expected '$(oneline "$VERSION")'" >&2
    found=1
  fi
  ((found == 0)) || die "$file: invalid release declaration"
  echo "$file: valid release declaration of $component $version"
done
