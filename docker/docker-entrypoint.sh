#!/bin/bash

# Docker entrypoint: dev user (image USER); optional sshd on port 2222 (no root/caps).
# Immutable toolchains: TOOLS_PREFIX on /tools (read-only). Mutable caches: ~/.cache.

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

    export CARGO_HOME="$HOME/.cache/cargo"
    export UV_CACHE_DIR="$HOME/.cache/uv"
    export XDG_CACHE_HOME="$HOME/.cache"
    export RUSTUP_HOME="$TOOLS_PREFIX/.rustup"
    export RUSTUP_NO_UPDATE=1

    if [ -d "$TOOLS_PREFIX/.cargo/bin" ]; then
        mkdir -p "$HOME/.cargo"
        ln -sfn "$TOOLS_PREFIX/.cargo/bin" "$HOME/.cargo/bin"
    fi

    if [ -d "$TOOLS_PREFIX/.rustup" ]; then
        ln -sfn "$TOOLS_PREFIX/.rustup" "$HOME/.rustup"
    fi

    export PATH="$TOOLS_PREFIX/.cargo/bin:$TOOLS_PREFIX/.local/bin:${PATH:-}"
    export CARGO_HOME RUSTUP_HOME UV_CACHE_DIR XDG_CACHE_HOME RUSTUP_NO_UPDATE PATH
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

if [ -f ~/.profile ]; then
    # shellcheck disable=SC1090
    source ~/.profile
fi

start_sshd

echo "c0dev ready"
exec tail -f /dev/null
