# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
git status -s | egrep "^[AM]" | cut -c4- | xargs -0 | egrep .

