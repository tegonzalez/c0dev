#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/c0-preflight.XXXXXX")"
FIXTURE="$TMP/c0dev"
STUB="$TMP/stub"
LOG="$TMP/log"
READY="$TMP/docker-ready"
DOWN_OUT="$TMP/build-down.out"
STOP_OUT="$TMP/stop.out"
STATUS_OUT="$TMP/status.out"
DOCTOR_MISSING_OUT="$TMP/doctor-missing.out"

mkdir -p "$FIXTURE" "$STUB" "$FIXTURE/bin"
cp "$ROOT/bin/c0" "$FIXTURE/bin/c0"
cp -R "$ROOT/docker" "$FIXTURE/docker"
chmod +x "$FIXTURE/bin/c0"
touch "$FIXTURE/.claude.json" "$TMP/.gitconfig"
cat >"$FIXTURE/docker/docker-compose.local.yaml" <<'EOF'
services:
  c0dev:
    environment:
      C0_TEST_LOCAL_COMPOSE: "1"
EOF

grep -q 'ENTRYPOINT \["/usr/local/bin/docker-entrypoint.sh"\]' "$FIXTURE/docker/Dockerfile"
grep -q '^USER dev$' "$FIXTURE/docker/Dockerfile"
! grep -q 'bubblewrap' "$FIXTURE/docker/Dockerfile"
! grep -q 'gosu' "$FIXTURE/docker/Dockerfile"
grep -q 'refusing to replace non-symlink' "$FIXTURE/docker/docker-entrypoint.sh"
! grep -q 'GOSU_BIN' "$FIXTURE/docker/docker-entrypoint.sh"
! grep -q 'C0_HOST_SSH_AUTH_SOCK' "$FIXTURE/docker/docker-entrypoint.sh"
! grep -q 'usermod' "$FIXTURE/docker/docker-entrypoint.sh"
! grep -q 'UNIX-LISTEN' "$FIXTURE/docker/docker-entrypoint.sh"
! grep -q 'SSH_AUTH_SOCK' "$FIXTURE/docker/docker-compose.public.yaml"
grep -q 'SSH_AUTH_SOCK: /home/dev/.ssh-auth.sock' "$FIXTURE/docker/docker-compose.ssh-auth.yaml"
grep -q 'C0_SSH_AUTH_SOCK_GID' "$FIXTURE/docker/docker-compose.ssh-auth.yaml"
grep -q 'create_host_path: false' "$FIXTURE/docker/docker-compose.ssh-auth.yaml"

cat >"$STUB/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
    info)
        if [[ -f "${C0_TEST_DOCKER_READY_FILE:-}" ]]; then
            exit 0
        fi
        echo "failed to connect to Docker at unix:///Users/test/.orbstack/run/docker.sock" >&2
        exit 1
        ;;
    context)
        echo "unix:///Users/test/.orbstack/run/docker.sock"
        ;;
    compose)
        echo "docker compose $*" >>"${C0_TEST_LOG:?}"
        case "$*" in
            *" ps -q c0dev"*|*" ps -aq c0dev"*)
                echo "container123"
                ;;
            *" ps --format "*)
                echo "c0dev: running"
                ;;
            *" exec -T -u 1000 c0dev "*)
                echo "ok:256 SHA256:test-key test@example.com (ED25519)"
                ;;
        esac
        ;;
    volume)
        case "${2:-}" in
            inspect) exit 1 ;;
            *) echo "docker $*" >>"${C0_TEST_LOG:?}" ;;
        esac
        ;;
    *)
        if [[ "${1:-}" == "inspect" && "$*" == *"NetworkSettings.Ports"* ]]; then
            echo "3000"
            exit 0
        fi
        if [[ "${1:-}" == "inspect" && "$*" == *"c0dev.security_mode"* ]]; then
            echo "permissive"
            exit 0
        fi
        echo "docker $*" >>"${C0_TEST_LOG:?}"
        ;;
esac
EOF
chmod +x "$STUB/docker"

cat >"$STUB/ssh-add" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "-l" ]]; then
    echo "256 SHA256:test-key test@example.com (ED25519)"
    exit 0
fi

echo "unexpected ssh-add $*" >&2
exit 1
EOF
chmod +x "$STUB/ssh-add"

cat >"$STUB/open" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "-a" && "${2:-}" == "OrbStack" ]]; then
    echo "open OrbStack" >>"${C0_TEST_LOG:?}"
    touch "${C0_TEST_DOCKER_READY_FILE:?}"
    exit 0
fi

echo "unexpected open $*" >&2
exit 1
EOF
chmod +x "$STUB/open"

cat >"$STUB/uname" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "-s" ]]; then
    echo "Darwin"
    exit 0
fi

command -p uname "$@"
EOF
chmod +x "$STUB/uname"

run_c0() {
    HOME="$TMP" \
    PATH="$STUB:$PATH" \
    C0_SECCOMP_NOTIFY=0 \
    C0_DOCKER_START_TIMEOUT=1 \
    C0_TEST_LOG="$LOG" \
    C0_TEST_DOCKER_READY_FILE="$READY" \
    "$FIXTURE/bin/c0" "$@"
}

touch "$READY"
if run_c0 doctor >"$DOCTOR_MISSING_OUT" 2>&1; then
    echo "expected doctor to fail when host paths are missing" >&2
    exit 1
fi
grep -q "host path validation failed" "$DOCTOR_MISSING_OUT"
grep -q "run:.*c0 doctor --fix" "$DOCTOR_MISSING_OUT"
rm -f "$READY"

if C0_DOCKER_AUTOSTART=0 run_c0 build >"$DOWN_OUT" 2>&1; then
    echo "expected build to stop at Docker preflight" >&2
    exit 1
fi
test -d "$FIXTURE/.cache"
grep -q "Host paths: created missing directories" "$DOWN_OUT"
grep -q "Docker daemon unavailable" "$DOWN_OUT"

run_c0 stop >"$STOP_OUT" 2>&1
grep -q "open OrbStack" "$LOG"
grep -q "docker-compose.local.yaml" "$LOG"
grep -q "Docker: .*ready" "$STOP_OUT"

(
    export SSH_AUTH_SOCK="$TMP/agent.sock"
    run_c0 status >"$STATUS_OUT" 2>&1
)
test ! -e "$FIXTURE/docker/.compose.ssh-auth.yaml"
grep -q "docker-compose.ssh-auth.yaml" "$LOG"
grep -q "/home/dev/.ssh-auth.sock" "$STATUS_OUT"
grep -q "/run/host-services/ssh-auth.sock" "$STATUS_OUT"
! grep -q "$TMP/agent.sock" "$STATUS_OUT"
grep -q "gid 67278" "$STATUS_OUT"
! grep -q "/tmp/c0dev-ssh-agent.sock" "$STATUS_OUT"
! grep -q "c0dev-ssh-auth.sock" "$FIXTURE/bin/c0"
grep -q "host:.*reachable" "$STATUS_OUT"
grep -q "container:.*reachable" "$STATUS_OUT"

(
    export SSH_AUTH_SOCK="$TMP/agent.sock"
    export C0_SSH_AUTH_SOCK_GID=1234
    run_c0 status >"$STATUS_OUT" 2>&1
)
grep -q "gid 1234" "$STATUS_OUT"

mkdir -p "$FIXTURE/projects/my app"
: >"$LOG"
(
    cd "$FIXTURE/projects/my app"
    run_c0 sh >/dev/null 2>&1
    run_c0 root >/dev/null 2>&1
)
grep -Fq 'cd -- /home/dev/projects/my\ app && exec bash -l' "$LOG"
grep -Fq 'cd -- /home/dev/projects/my\ app && exec bash' "$LOG"

echo "c0-preflight: ok"
