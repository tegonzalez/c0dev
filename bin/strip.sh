#!/bin/bash

# Strip script: Clean up text files by removing trailing spaces and converting Unicode characters
# Usage: ./strip.sh file1 [file2 file3 ...]

if [ $# -eq 0 ]; then
    echo "Usage: $0 file1 [file2 file3 ...]"
    echo "Cleans up text files by:"
    echo "  - Removing trailing spaces"
    echo "  - Converting Unicode dashes to standard hyphens"
    echo "  - Converting Unicode spaces to regular spaces"
    echo "  - Converting bullets to asterisks"
    echo "  - Converting arrows to ->"
    exit 1
fi

sed-no-backup() {
    local file="$1"
    # test for gnu sed vs. osx sed
    if sed --version > /dev/null 2>&1; then
        local backup_arg="-i"
    else
        local backup_arg="-i ''"
    fi

    echo "Processing: $file"
    # Use sed -i with empty backup extension to edit in-place without creating backup
    sed $backup_arg "s/[ ][ ]*\$//; \
        s/–/-/g; \
        s/ / /g; \
        s/‑/-/g; \
        s/—/-/g; \
        s/•/*/g; \
        s/→/->/g; \
        s/➜/->/g;" "$file"
}

# Process each file argument
for file in "$@"; do
    if [ ! -f "$file" ]; then
        echo "Warning: File '$file' not found, skipping..."
        continue
    fi
    sed-no-backup "$file"
done

echo "Done processing $# file(s)"
