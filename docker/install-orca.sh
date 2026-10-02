#!/bin/sh
# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
set -eu

orca_version=1.4.192
orca_sha256=eab7ea7110a4a89e52573331a613c15bfc30ec5bfaf1f7af2e86db7ce528e508
orca_url="https://github.com/stablyai/orca/releases/download/v${orca_version}/orca-ide_${orca_version}_arm64.deb"

architecture="$(dpkg --print-architecture)"
if [ "$architecture" != arm64 ]; then
    echo "error: Orca ${orca_version} installer requires arm64; image architecture is ${architecture}" >&2
    exit 1
fi

orca_deb="$(mktemp /tmp/orca-ide.XXXXXX.deb)"
cleanup() {
    rm -f "$orca_deb"
}
trap cleanup 0 HUP INT TERM

curl --fail --location --retry 3 --retry-all-errors \
    --output "$orca_deb" \
    "$orca_url"

printf '%s  %s\n' "$orca_sha256" "$orca_deb" | sha256sum --check -
chmod 0644 "$orca_deb"
apt-get install -y "$orca_deb"
