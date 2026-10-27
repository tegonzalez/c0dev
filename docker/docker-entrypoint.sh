#!/bin/bash
# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT

# Docker entrypoint: dev user (image USER); optional sshd on port 2222 (no root/caps).
# Immutable toolchains: TOOLS_PREFIX on /tools (read-only). Mutable home overlays are mounted by c0.

set -e

setup_dev_tools() {
    if [ -z "$TOOLS_PREFIX" ]; then
        echo "warning: TOOLS_PREFIX not set, tools may be missing" >&2
        return 0
    fi

    if [ ! -d "$TOOLS_PREFIX" ]; then
        echo "error: TOOLS_PREFIX does not exist: $TOOLS_PREFIX" >&2
        echo "Run 'c0 build' to create tools for current TOOLS_ID (Dockerfile.base + Dockerfile.tools)" >&2
        exit 1
    fi

    if [ ! -f "$TOOLS_PREFIX/.c0dev-complete" ]; then
        echo "error: tools incomplete at: $TOOLS_PREFIX" >&2
        echo "Run 'c0 build' to rebuild tools" >&2
        exit 1
    fi

    mkdir -p "$HOME/.cache/cargo" "$HOME/.cache/uv"

    if [ -d "$TOOLS_PREFIX/.cargo/bin" ]; then
        mkdir -p "$HOME/.cargo"
        ln -sfn "$TOOLS_PREFIX/.cargo/bin" "$HOME/.cargo/bin"
    fi

    if [ -d "$TOOLS_PREFIX/.rustup" ]; then
        ln -sfn "$TOOLS_PREFIX/.rustup" "$HOME/.rustup"
    fi

}

wait_for_home_overlays() {
    local policy_file=/etc/c0dev/home-overlays.conf
    local guest_rel tools_rel extra target fstype
    local attempts=0 pending

    [ -r "$policy_file" ] || {
        echo "error: home overlay policy missing: $policy_file" >&2
        exit 1
    }

    while [ "$attempts" -lt 150 ]; do
        # The host launcher lower is RO; the writable guest view is mounted by c0.
        pending=0
        # Retained pre-upgrade guests still have the old direct bin mount.
        # The host validates that layout before restoring their home overlays.
        if mountpoint -q /run/c0/host-bin; then
            fstype="$(findmnt -T "$HOME/bin" -n -o FSTYPE 2>/dev/null || true)"
            { mountpoint -q "$HOME/bin" && [ "$fstype" = overlay ]; } || pending=$((pending + 1))
        elif ! mountpoint -q "$HOME/bin"; then
            pending=$((pending + 1))
        fi
        while IFS='|' read -r guest_rel tools_rel extra; do
            case "$guest_rel" in
                ''|'#'*) continue ;;
            esac
            target="$HOME/$guest_rel"
            fstype="$(findmnt -T "$target" -n -o FSTYPE 2>/dev/null || true)"
            { mountpoint -q "$target" && [ "$fstype" = overlay ]; } || pending=$((pending + 1))
        done <"$policy_file"
        [ "$pending" -eq 0 ] && return 0
        attempts=$((attempts + 1))
        sleep 0.2
    done

    echo "error: timed out waiting for c0 home overlays" >&2
    exit 1
}

start_sshd() {
    local ssh_dir="$HOME/.ssh"

    if [ ! -f "$ssh_dir/authorized_keys" ]; then
        return 0
    fi
    if [ ! -x /usr/sbin/sshd ]; then
        echo "warning: openssh-server missing in image; inbound SSH disabled" >&2
        return 0
    fi

    mkdir -p /run/sshd 2>/dev/null || true
    if [ -f "$ssh_dir/sshd_config" ]; then
        /usr/sbin/sshd -f "$ssh_dir/sshd_config" || \
            echo "warning: sshd failed to start" >&2
    fi
}

setup_dev_tools
wait_for_home_overlays

if [ -f ~/.profile ]; then
    # shellcheck disable=SC1090
    source ~/.profile
fi

start_sshd

echo "c0dev ready"
exec tail -f /dev/null
