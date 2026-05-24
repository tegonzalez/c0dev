#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/c0 entrypoints.XXXXXX")"

test -f "$ROOT/Makefile"
grep -q '^doctor:' "$ROOT/Makefile"
grep -q '^fix:' "$ROOT/Makefile"
grep -q '^build:' "$ROOT/Makefile"
grep -q '^start:' "$ROOT/Makefile"
grep -q '^restart:' "$ROOT/Makefile"
grep -q '^stop:' "$ROOT/Makefile"
grep -q '^status:' "$ROOT/Makefile"
grep -q '^sh:' "$ROOT/Makefile"
grep -q '^root:' "$ROOT/Makefile"
grep -q '^logs:' "$ROOT/Makefile"
grep -q '^test:' "$ROOT/Makefile"
grep -q 'PUBLIC_TESTS' "$ROOT/Makefile"
grep -q '^-include Makefile.local' "$ROOT/Makefile"

for shim in c0-sh c0-root c0-status; do
    test -x "$ROOT/bin/$shim"
done

grep -q 'exec "$SCRIPT_DIR/c0" sh "$@"' "$ROOT/bin/c0-sh"
grep -q 'exec "$SCRIPT_DIR/c0" root "$@"' "$ROOT/bin/c0-root"
grep -q 'exec "$SCRIPT_DIR/c0" status "$@"' "$ROOT/bin/c0-status"

mkdir -p "$TMP/c0 dev/bin"
cp "$ROOT/env.sh" "$TMP/c0 dev/env.sh"
printf '#!/usr/bin/env bash\nprintf "stub-c0\\n"\n' >"$TMP/c0 dev/bin/c0"
chmod +x "$TMP/c0 dev/bin/c0"
test "$("$TMP/c0 dev/env.sh" -lc 'c0')" = "stub-c0"

echo "c0-entrypoints: ok"
