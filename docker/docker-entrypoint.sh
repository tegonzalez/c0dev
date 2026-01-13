#!/bin/bash

# Docker entrypoint script that handles both interactive and daemon modes
# This script runs as the dev user (set by USER directive in Dockerfile)

# Validate and set up tools symlinks from TOOLS_PREFIX (injected by c0)
if [ -n "$TOOLS_PREFIX" ]; then
    # Fail fast if tools don't exist
    if [ ! -d "$TOOLS_PREFIX" ]; then
        echo "error: TOOLS_PREFIX does not exist: $TOOLS_PREFIX" >&2
        echo "Run 'c0 build' to create tools for current Dockerfile" >&2
        exit 1
    fi

    if [ ! -f "$TOOLS_PREFIX/.c0dev-complete" ]; then
        echo "error: tools incomplete at: $TOOLS_PREFIX" >&2
        echo "Run 'c0 build' to rebuild tools" >&2
        exit 1
    fi

    # Create symlinks so tools appear at expected locations (~/.cargo, etc.)
    for dir in .cargo .rustup .local; do
        if [ -d "$TOOLS_PREFIX/$dir" ]; then
            rm -rf "$HOME/$dir" 2>/dev/null
            ln -sfn "$TOOLS_PREFIX/$dir" "$HOME/$dir"
        fi
    done

    # Set env vars as fallback
    export CARGO_HOME="$HOME/.cargo"
    export RUSTUP_HOME="$HOME/.rustup"
else
    echo "warning: TOOLS_PREFIX not set, tools may be missing" >&2
fi

# Source profile for environment setup
if [ -f ~/.profile ]; then
    source ~/.profile
fi

# Check if we're running interactively (tty attached)
if [ -t 0 ]; then
    exec /bin/bash -l
else
    echo "c0dev ready"
    exec tail -f /dev/null
fi
