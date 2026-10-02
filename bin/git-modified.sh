# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
git status -s | egrep "^.[M]" | cut -c4- | xargs -0 | egrep .

