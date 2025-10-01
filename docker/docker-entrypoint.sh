#!/bin/bash

# Docker entrypoint script that handles both interactive and daemon modes
# This script runs as the bun user (set by USER directive in Dockerfile)

# Source profile for environment setup
if [ -f ~/.profile ]; then
    source ~/.profile
fi

# Check if we're running interactively (tty attached)
if [ -t 0 ]; then
    # Interactive mode - start bash
    echo "Starting interactive bash session..."
    exec /bin/bash
else
    # Daemon mode - keep container running
    echo "Container started in daemon mode."
    echo "Use 'docker exec -it <container> bash' to access interactive shell."
    # Keep container alive indefinitely
    exec tail -f /dev/null
fi
