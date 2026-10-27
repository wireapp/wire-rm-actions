#!/usr/bin/env bash
# Install crane (google/go-containerregistry) for this job when none is on
# PATH: the release archive of CRANE_VERSION for this runner, checked against
# the sha256 given, unpacked into DEST. A sha256 mismatch fails before anything
# is unpacked; nothing is built and no module proxy is involved.
#
# Environment:
#   CRANE_VERSION   release tag, vX.Y.Z (required)
#   CRANE_SHA256    sha256 of go-containerregistry_<OS>_<arch>.tar.gz for this
#                   runner's OS and architecture (required)
#   DEST            directory receiving the crane binary (required)
#   CRANE_BASE_URL  where the archives are (default: the GitHub releases of
#                   google/go-containerregistry; a file:// URL in the tests)
set -euo pipefail
export LC_ALL=C
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

CRANE_VERSION=${CRANE_VERSION:-}
CRANE_SHA256=${CRANE_SHA256:-}
DEST=${DEST:-}
CRANE_BASE_URL=${CRANE_BASE_URL:-https://github.com/google/go-containerregistry/releases/download}

if command -v crane >/dev/null 2>&1; then
  echo "crane is on PATH: $(command -v crane), nothing installed"
  exit 0
fi

[[ $CRANE_VERSION =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "crane-version must be vX.Y.Z (got: '$CRANE_VERSION')"
[[ $CRANE_SHA256 =~ ^[0-9a-f]{64}$ ]] || die "crane-sha256 must be the 64-character hex sha256 of the release archive (got: '$CRANE_SHA256')"
[[ -n $DEST ]] || die "DEST is required"

case "$(uname -s)" in
  Linux) os=Linux ;;
  Darwin) os=Darwin ;;
  *) die "unsupported OS $(uname -s): install crane on the runner and put it on PATH" ;;
esac
case "$(uname -m)" in
  x86_64 | amd64) arch=x86_64 ;;
  aarch64 | arm64) arch=arm64 ;;
  *) die "unsupported architecture $(uname -m): install crane on the runner and put it on PATH" ;;
esac

archive="go-containerregistry_${os}_${arch}.tar.gz"
url="${CRANE_BASE_URL%/}/${CRANE_VERSION}/${archive}"
proto='=https'
[[ $CRANE_BASE_URL == file://* ]] && proto='=file'

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

echo "crane ${CRANE_VERSION} for ${os}/${arch} from ${url}"
curl --fail --silent --show-error --location --proto "$proto" --tlsv1.2 --retry 3 \
  -o "$tmp/$archive" "$url" || die "could not download $url"
got=$(sha256_of "$tmp/$archive")
[[ $got == "$CRANE_SHA256" ]] || die "$archive: sha256 $got, expected $CRANE_SHA256 (crane-sha256 must match crane-version and this runner's OS and architecture)"
tar -xzf "$tmp/$archive" -C "$tmp" crane || die "$archive holds no crane binary"
mkdir -p "$DEST"
chmod 0755 "$tmp/crane"
mv -f "$tmp/crane" "$DEST/crane"
echo "crane ${CRANE_VERSION} installed in ${DEST} (sha256 of the archive checked)"
