# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
docker ps --format '{{.Image}} {{.ID}}' | egrep "^f7-node\s" | head -n1 | cut -f2 -d' '
