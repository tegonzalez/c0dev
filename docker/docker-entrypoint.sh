#!/bin/bash

DEV_HOME="${DEV_HOME:-/home/dev}"

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
            dst="$DEV_HOME/$dir"
            src="$TOOLS_PREFIX/$dir"
            if [ -L "$dst" ]; then
                rm -f "$dst"
            elif [ -e "$dst" ]; then
                echo "error: refusing to replace non-symlink: $dst" >&2
                echo "Remove or move it, then restart c0dev." >&2
                exit 1
            fi
            ln -s "$src" "$dst"
        fi
    done

    # Set env vars as fallback
    export CARGO_HOME="$DEV_HOME/.cargo"
    export RUSTUP_HOME="$DEV_HOME/.rustup"
else
    echo "warning: TOOLS_PREFIX not set, tools may be missing" >&2
fi

# Check if we're running interactively (tty attached)
if [ -t 0 ]; then
    exec /bin/bash -l
else
    echo "c0dev ready"
    exec tail -f /dev/null
fi
