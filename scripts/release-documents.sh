#!/usr/bin/env bash
# Gather the release documents of a build (ADR-0020 sections 2 and 3,
# ADR-0021 section 1) and print the `documents` object of its release
# manifest.
#
# Release note, read from the repository: <PUBLICATION_DIR>/release-note.md
# (ADR-0020, publication/), the note of the version the build leads to
# (1.41.4 for 1.41.4-rc.1 or for the dev build 1.41.4-rc.1.20261014120000.gabcdef0).
#   - ga, alpha, beta, rc: copied to <OUT_DIR>/release-note.md. A GA without
#     a note fails, a pre-release warns and goes without.
#   - dev: never copied nor required: referenced by its repository path, a
#     missing note is a warning.
#   - RELEASE_NOTE (the release_note dispatch input): with
#     NOTE_INPUT=override it replaces the repository note of a release; with
#     NOTE_INPUT=ignore (default) it is ignored with a warning.
#
# Release declaration (releases only, never for dev): the
# RELEASE_DECLARATION input, written byte for byte to
# <OUT_DIR>/release-declaration.json (the release manager sends its canonical
# form and compares the hash); without it, <PUBLICATION_DIR>/declaration.json,
# written as canonical JSON. A GA without one fails, a pre-release goes
# without. The declaration is validated (release-declaration.sh) with its
# component and the base version, the GA its pre-releases lead to.
#
# Environment:
#   RELEASE_TYPE   ga | alpha | beta | rc | dev                       required
#   VERSION        the version, without "v"                          required
#   COMPONENT      release manager component id                       required
#   RELEASE_NOTE, NOTE_INPUT (ignore | override)                      optional
#   RELEASE_DECLARATION  JSON text of the declaration                 optional
#   PUBLICATION_DIR  folder of the release files (default publication)
#   OUT_DIR        where the documents are written (default: .)
#
# Outputs (stdout and $GITHUB_OUTPUT): note-file, note-path, note-sha256,
# note-source, declaration-file, declaration-sha256, declaration-source
# (empty when absent) and documents-json, the `documents` object of the
# manifest ({} when empty, never null).
set -euo pipefail
export LC_ALL=C
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

RELEASE_TYPE=${RELEASE_TYPE:-}
VERSION=${VERSION:-}
COMPONENT=${COMPONENT:-}
RELEASE_NOTE=${RELEASE_NOTE:-}
NOTE_INPUT=${NOTE_INPUT:-ignore}
RELEASE_DECLARATION=${RELEASE_DECLARATION:-}
OUT_DIR=${OUT_DIR:-.}
PUBLICATION_DIR=${PUBLICATION_DIR:-publication}

[[ -n $COMPONENT ]] || die "COMPONENT is required"
case $RELEASE_TYPE in
  ga | alpha | beta | rc)
    [[ $VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+(-(alpha|beta|rc)\.[0-9]+)?$ ]] ||
      die "VERSION '$VERSION' is not X.Y.Z or X.Y.Z-<alpha|beta|rc>.N"
    ;;
  dev)
    [[ $VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+- ]] || die "VERSION '$VERSION' is not a dev version (X.Y.Z-...)"
    ;;
  *) die "RELEASE_TYPE must be one of ga, alpha, beta, rc, dev (got: '$RELEASE_TYPE')" ;;
esac
case $NOTE_INPUT in
  ignore | override) ;;
  *) die "NOTE_INPUT must be ignore or override (got: '$NOTE_INPUT')" ;;
esac
mkdir -p "$OUT_DIR"

base_version=${VERSION%%-*}
expected_note=$PUBLICATION_DIR/release-note.md
publication_declaration=$PUBLICATION_DIR/declaration.json

# --- Release note -------------------------------------------------------
note_path=""
if [[ -f $expected_note ]] && grep -q '[^[:space:]]' "$expected_note"; then
  note_path=$expected_note
fi

note_file="" note_sha256="" note_source=""
if [[ $RELEASE_TYPE == dev ]]; then
  [[ -z $RELEASE_NOTE ]] || warn "RELEASE_NOTE is ignored for a dev build"
  if [[ -n $note_path ]]; then
    note_file=$note_path
    note_sha256=$(sha256_of "$note_path")
    note_source=repository
    echo "Release note of $base_version: $note_path"
  else
    echo "::warning title=No release note for $base_version::$expected_note is missing or empty: the dev build $VERSION goes without, a GA of $base_version will require it."
    summary "- :warning: no release note for $base_version (\`$expected_note\`): a GA will require it"
  fi
else
  if [[ -n $RELEASE_NOTE && $NOTE_INPUT == override ]]; then
    printf '%s\n' "$RELEASE_NOTE" >"$OUT_DIR/release-note.md"
    note_source=input
    echo "Release note: the release_note input (${#RELEASE_NOTE} characters)"
  elif [[ -n $note_path ]]; then
    [[ -z $RELEASE_NOTE ]] ||
      warn "the release_note input (${#RELEASE_NOTE} characters) is ignored: the release note of $COMPONENT is read from the repository, $note_path"
    cp "$note_path" "$OUT_DIR/release-note.md"
    note_source=repository
    echo "Release note: $note_path"
  elif [[ $RELEASE_TYPE == ga ]]; then
    die "no release note for GA $VERSION: expected $expected_note in the repository. Merge it on the source branch and prepare again"
  else
    warn "no release note for $VERSION (expected $expected_note): the $RELEASE_TYPE goes without, the GA will require it"
  fi
  if [[ -n $note_source ]]; then
    note_file=release-note.md
    note_sha256=$(sha256_of "$OUT_DIR/release-note.md")
  fi
fi

# --- Release declaration (releases only) --------------------------------
declaration_file="" declaration_sha256="" declaration_source=""
if [[ $RELEASE_TYPE == dev ]]; then
  [[ -z $RELEASE_DECLARATION ]] || warn "RELEASE_DECLARATION is ignored for a dev build"
elif [[ -n $RELEASE_DECLARATION ]]; then
  # Bytes kept as received: the release manager hashes what it sent.
  printf '%s' "$RELEASE_DECLARATION" >"$OUT_DIR/release-declaration.json"
  declaration_source=release_manager
elif [[ -f $publication_declaration ]]; then
  # Canonical JSON: one line, sorted keys, non-ASCII kept.
  jq -cS . "$publication_declaration" | tr -d '\n' >"$OUT_DIR/release-declaration.json.tmp" ||
    die "$publication_declaration is not valid JSON"
  mv "$OUT_DIR/release-declaration.json.tmp" "$OUT_DIR/release-declaration.json"
  declaration_source=repository
elif [[ $RELEASE_TYPE == ga ]]; then
  die "no release declaration for GA $VERSION: the release_declaration input sends it, or $publication_declaration provides it (ADR-0020 rule 5)"
else
  echo "No release declaration for $VERSION: optional for a $RELEASE_TYPE."
fi

if [[ -n $declaration_source ]]; then
  declaration_file=release-declaration.json
  # The declaration names the GA version its pre-releases share.
  COMPONENT=$COMPONENT VERSION=$base_version "$here/release-declaration.sh" "$OUT_DIR/$declaration_file" ||
    die "the release declaration ($declaration_source) is invalid for $COMPONENT $VERSION; see the lines above"
  declaration_sha256=$(sha256_of "$OUT_DIR/$declaration_file")
  echo "Release declaration: $declaration_source (sha256 $declaration_sha256)"
fi

documents_json=$(jq -cn \
  --arg nf "$note_file" --arg ns "$note_sha256" --arg nsrc "$note_source" \
  --arg df "$declaration_file" --arg ds "$declaration_sha256" --arg dsrc "$declaration_source" '
  {}
  + (if $nf != "" then {release_note: {file: $nf, sha256: $ns, source: $nsrc}} else {} end)
  + (if $df != "" then {release_declaration: {file: $df, sha256: $ds, source: $dsrc}} else {} end)')

emit note-file "$note_file"
emit note-path "$note_path"
emit note-sha256 "$note_sha256"
emit note-source "$note_source"
emit declaration-file "$declaration_file"
emit declaration-sha256 "$declaration_sha256"
emit declaration-source "$declaration_source"
emit documents-json "$documents_json"
