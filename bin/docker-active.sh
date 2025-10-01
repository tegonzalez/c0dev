docker ps --format '{{.Image}} {{.ID}}' | egrep "^f7-node\s" | head -n1 | cut -f2 -d' '
