#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/c0-activate-path.XXXXXX")"
FIXTURE="$TMP/c0dev"

mkdir -p \
    "$FIXTURE/bin" \
    "$FIXTURE/.cargo/bin" \
    "$FIXTURE/.local/bin" \
    "$FIXTURE/local-tools/bin"

FIXTURE_REAL="$(realpath "$FIXTURE")"

cp "$ROOT/bin/activate" "$FIXTURE/bin/activate"
printf 'prepend_path "%s"\n' "$FIXTURE_REAL/local-tools/bin" >"$FIXTURE/bin/activate.local"

(
    HOME="$FIXTURE"
    . "$FIXTURE/bin/activate"

    case ":$PATH:" in
        *":$FIXTURE_REAL/.cargo/bin:"*) ;;
        *) echo "missing .cargo/bin in PATH" >&2; exit 1 ;;
    esac

    case ":$PATH:" in
        *":$FIXTURE_REAL/.local/bin:"*) ;;
        *) echo "missing .local/bin in PATH" >&2; exit 1 ;;
    esac

    case ":$PATH:" in
        *":$FIXTURE_REAL/bin:"*) ;;
        *) echo "missing bin in PATH" >&2; exit 1 ;;
    esac

    case ":$PATH:" in
        *":$FIXTURE_REAL/local-tools/bin:"*) ;;
        *) echo "missing activate.local path in PATH" >&2; exit 1 ;;
    esac

    case ":$PATH:" in
        *":$FIXTURE_REAL/local-tools/bin:$FIXTURE_REAL/bin:"*) ;;
        *) echo "activate.local should be able to override repo bin" >&2; exit 1 ;;
    esac
)

echo "c0-activate-path: ok"
