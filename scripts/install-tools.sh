#!/usr/bin/env bash
# Install the pinned lint, scan and chart tools into .tools/bin (make tools):
# each archive is downloaded from the project's release page over https,
# checked against its sha256 below, then unpacked. A tool already installed
# from the same archive is not downloaded again.
#
# To upgrade a tool, change its version and its three sha256 together, taken
# from the checksums the project publishes with the release.
#
# The sha256 variables are read through ${!var}:
# shellcheck disable=SC2034
set -euo pipefail
export LC_ALL=C

ACTIONLINT_VERSION=1.7.12
# actionlint_<version>_checksums.txt
ACTIONLINT_SHA256_linux_amd64=8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8
ACTIONLINT_SHA256_darwin_arm64=aba9ced2dee8d27fecca3dc7feb1a7f9a52caefa1eb46f3271ea66b6e0e6953f
ACTIONLINT_SHA256_darwin_amd64=5b44c3bc2255115c9b69e30efc0fecdf498fdb63c5d58e17084fd5f16324c644

SHELLCHECK_VERSION=0.11.0
# No checksums file is published: the asset digests GitHub shows on the release.
SHELLCHECK_SHA256_linux_amd64=b7af85e41cc99489dcc21d66c6d5f3685138f06d34651e6d34b42ec6d54fe6f6
SHELLCHECK_SHA256_darwin_arm64=339b930feb1ea764467013cc1f72d09cd6b869ebf1013296ba9055ab2ffbd26f
SHELLCHECK_SHA256_darwin_amd64=c2c15e08df0e8fbc374c335b230a7ee958c313fa5714817a59aa59f1aa594f51

GITLEAKS_VERSION=8.30.1
# gitleaks_<version>_checksums.txt
GITLEAKS_SHA256_linux_amd64=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb
GITLEAKS_SHA256_darwin_arm64=b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5
GITLEAKS_SHA256_darwin_amd64=dfe101a4db2255fc85120ac7f3d25e4342c3c20cf749f2c20a18081af1952709

HELM_VERSION=4.3.0
# helm-v<version>-<os>-<arch>.tar.gz.sha256sum, on get.helm.sh (the download
# host the helm release page links to)
HELM_SHA256_linux_amd64=86584a54def73570558f66f5111cc53dfed56689637ae32c1201205d494f54fb
HELM_SHA256_darwin_arm64=d3870437e1e95b67f8edbde964156c84a26503f560821d40c542441658934fba
HELM_SHA256_darwin_amd64=347a784877e0e20eac865e8d1c36a80f6bb0861d6f29abd34defb6570ef95d92

YQ_VERSION=4.54.1
# The SHA-256 column of the release's checksums file (column order in
# checksums_hashes_order).
YQ_SHA256_linux_amd64=e68a456f90c577af3fe4960184b3a3cf5c461e0348407c10f107da3a5fec8972
YQ_SHA256_darwin_arm64=60d0c91aa8bf4030d38e80bb05f84c20be2e955f24d62b2e55d15ad643fa7afa
YQ_SHA256_darwin_amd64=b2cc367e9f5491b3b9b191aa19ba3a3163daf99d84f90bc7bd8918010a66e69a

root=$(cd "$(dirname "$0")/.." && pwd)
bin="$root/.tools/bin"

die() {
  echo "install-tools: $*" >&2
  exit 1
}

case "$(uname -s)/$(uname -m)" in
Linux/x86_64) platform=linux_amd64 ;;
Darwin/arm64) platform=darwin_arm64 ;;
Darwin/x86_64) platform=darwin_amd64 ;;
*) die "unsupported platform $(uname -s)/$(uname -m)" ;;
esac

if command -v sha256sum >/dev/null; then
  sha256() { sha256sum "$1" | cut -d' ' -f1; }
else
  sha256() { shasum -a 256 "$1" | cut -d' ' -f1; }
fi

# install <tool> <archive url> <sha256> <path of the binary in the archive>
install() {
  local tool=$1 url=$2 want=$3 member=$4 stamp="$bin/.$1.sha256" got
  if [[ -x $bin/$tool && -f $stamp && $(<"$stamp") == "$want" ]]; then
    return 0
  fi
  echo "install-tools: $tool from $url"
  curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
    --retry 3 -o "$tmp/archive.tar.gz" "$url"
  got=$(sha256 "$tmp/archive.tar.gz")
  [[ $got == "$want" ]] || die "$tool: sha256 $got, expected $want"
  tar -xzf "$tmp/archive.tar.gz" -C "$tmp" "$member"
  chmod 0755 "$tmp/$member"
  mv -f "$tmp/$member" "$bin/$tool"
  echo "$want" >"$stamp"
}

mkdir -p "$bin"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

var=ACTIONLINT_SHA256_$platform
os=${platform%_*} arch=${platform#*_}
install actionlint \
  "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION}_${platform}.tar.gz" \
  "${!var}" actionlint

var=SHELLCHECK_SHA256_$platform
sc_arch=$arch
[[ $arch == amd64 ]] && sc_arch=x86_64
[[ $arch == arm64 ]] && sc_arch=aarch64
install shellcheck \
  "https://github.com/koalaman/shellcheck/releases/download/v${SHELLCHECK_VERSION}/shellcheck-v${SHELLCHECK_VERSION}.${os}.${sc_arch}.tar.gz" \
  "${!var}" "shellcheck-v${SHELLCHECK_VERSION}/shellcheck"

var=GITLEAKS_SHA256_$platform
gl_arch=$arch
[[ $arch == amd64 ]] && gl_arch=x64
install gitleaks \
  "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_${os}_${gl_arch}.tar.gz" \
  "${!var}" gitleaks

var=HELM_SHA256_$platform
install helm \
  "https://get.helm.sh/helm-v${HELM_VERSION}-${os}-${arch}.tar.gz" \
  "${!var}" "${os}-${arch}/helm"

var=YQ_SHA256_$platform
install yq \
  "https://github.com/mikefarah/yq/releases/download/v${YQ_VERSION}/yq_${platform}.tar.gz" \
  "${!var}" "./yq_${platform}"
