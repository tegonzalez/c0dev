# c0dev

A containerized development environment for AI-assisted coding and full-stack work, packaged as a reproducible Docker image with modern CLI tooling.

## Overview
- Portable workspace with assistants (Claude Code, Codex, OpenCode, Cursor) and polyglot toolchains
- Multi-stage image build that extracts heavy tooling to the host for reuse between rebuilds
- Opinionated defaults that mirror the author’s macOS-based setup for low-friction onboarding

## Release Status and Host Requirements
**⚠️ Alpha Release:** Validated on the author’s workstation only.
- macOS: Apple M-series Tahoe v26.0.1
- OrbStack: orbctl 2.0.2 (2000200)
- Terminal: Ghostty v1.2.0 (supports CMD+click URL auth)
- Xcode: Required to provide `infocmp` during image build

## Container Image Summary
- Base distro: Debian (downstream of `oven/bun:latest`)
- Approximate size: 2 GB total (Rustup toolchain accounts for ~1.3 GB)
- ~10 bin builder build time

## Tooling Inventory
### Built from Source (Cargo)
- `fd` 10.3.0 – fast file finder
- `ripgrep` 14.1.1 – recursive search
- `ast-grep` 0.39.4 – structural code search
- `zellij` 0.43.1 – terminal multiplexer
- `cargo-cache` – cargo cache management

### Installed via Package Managers
- Python: `uv`
- Bun globals: `@anthropic-ai/claude-code`, `@openai/codex`, `opencode-ai`
- System utilities: `build-essential`, `cmake`, `git`, `curl`, `wget`, `fzf`, `jq`, `yq`, `bc`, `bat`, `btop`, `iproute2`, `iputils-ping`, `net-tools`, `socat`, `netcat`, `vim`, `tmux`
- Rust toolchain: `rustup` with `wasm32-unknown-unknown` target (registry cache cleaned post-build)

## Quick Start Workflow
### Bootstrap the Workspace
1. Clone the repo: `git clone https://github.com/tegonzalez/c0dev.git`
2. Enter the project: `cd c0dev`
3. Load helper scripts into `PATH`: `./env.sh`
4. See available commands: `make help`
5. Run onboarding checks: `make fix`
6. Build the image: `c0 build` (first build takes ~10 minutes)

### Launch and Access the Container
- Start services: `c0 start`
- Open a shell as the dev user: `c0 sh` (auto-navigates to matching project directory)

## Installation

```bash
# Clone the repository
git clone https://github.com/tegonzalez/c0dev.git
cd c0dev

# Enter sub-shell for c0dev PATH
./env.sh

# Create missing repo-local host mount directories and check Docker
make fix

# Build the Docker image (~10 minutes)
c0 build
```

**Build Time**: Approximately 10 minutes for full build including Rust toolchain installation.

### What `c0 build` Does
1. Creates missing repo-local host mount directories and validates file mappings
2. Builds `tools-builder` stage with uv, Cursor CLI, and Rust tools
3. Extracts built tools into the shared Docker tools volume
4. Builds final Docker image with system packages and global tools
5. Installs terminfo for proper terminal emulation

## Usage

### Beginner Entrypoints

```bash
# Show the common workflow commands
make help

# Makefile targets are beginner-friendly wrappers around c0 commands
make build

# Compatibility wrappers for common c0 commands
c0-sh
c0-root
c0-status
```

### Service Management

```bash
# Start the development environment
c0 start

# Enter container as dev user (UID 1000)
c0 sh

# Enter container as root (UID 0)
# Note: Use 'c0 root' instead of sudo
c0 root

# Stop the environment
c0 stop

# Restart services
c0 restart

# View logs
c0 logs

# Check status
c0 status

# Rebuild (force with -f flag)
c0 build [-f]

# Check onboarding prerequisites; --fix creates missing repo-local host dirs
c0 doctor [--fix]
```

### Web Port Mapping
- The container listens on `guest:3000`. The host port is auto-selected per `c0dev` checkout.
- Auto-selection range: `3000–4000`. Allocation rule: first available port in the range (fills gaps).
- The selected mapping is printed on `c0 start`, `c0 restart`, and `c0 status` as `host:<port> -> guest:3000`.
- Override: `C0DEV_WEB_PORT=3001 c0 start`

### Local Compose Overrides
- Optional local Docker Compose overrides can live in `docker/docker-compose.local.yaml`.
- This file is ignored by git and is loaded after the public, security, and SSH-agent compose files.
- Use it for machine-specific mounts, environment variables, or service tweaks that should not be committed.

## Authenticate Assistants

### Claude Code
1. Run `claude setup-token` inside the container.
2. Follow the browser prompt (Ghostty users can CMD+click the URL) and approve long-term access.
 - from host: `open $(pbpaste 2>/dev/null | tr -d '\n' || echo '(paste URL)')`
3. Wait for the CLI to confirm the token was stored under `/home/dev/.claude.json` (persisted via the host volume).

### Codex CLI
Codex now supports device authentication; run `codex login --device-auth` and follow the prompts.

### OpenCode CLI
1. Run `opencode auth login` to start the interactive login.
2. Choose your provider (or supply a URL) and finish the browser flow when prompted.
3. The CLI saves credentials under `/home/dev/.config/opencode`, so future sessions reuse the same login.

## Volume Mappings
Persistent host ↔ container paths for credentials, tooling, and projects:
- `.claude/` → `/home/dev/.claude`
- `.config/` → `/home/dev/.config`
- `.codex/` → `/home/dev/.codex`
- `.cache/` → `/home/dev/.cache`
- `rules/` → `/home/dev/rules`
- `projects/` → `/home/dev/projects`
- `bin/` → `/home/dev/bin`
- `.claude.json` → `/home/dev/.claude.json`
- `~/.gitconfig` → `/home/dev/.gitconfig`
- `c0dev-tools-shared` Docker volume → `/tools`

These mappings keep credentials, tool installs, and in-progress work outside the ephemeral container filesystem.

## Environment Defaults
- Locale: `en_US.UTF-8`
- Timezone: `America/Los_Angeles` (`TZ` build arg overrides)
- Exposed ports: `host:<auto> -> guest:3000` (auto-selected in range `3000–4000`, override with `C0DEV_WEB_PORT`)
- LLM provider: Ollama at `http://host.docker.internal:11434`
- Default model: `gpt-oss:20b`

## Build Pipeline Highlights
1. Create missing repo-local host mount directories, then verify host files exist
2. Build `tools-builder` stage (uv, Cursor CLI, Rust tools)
3. Extract tool artifacts to the shared Docker tools volume
4. Assemble final runtime image with system packages and global CLIs
5. Install terminfo database for accurate terminal emulation

## Networking Notes
- Container has public network access with host bridging
- `host.docker.internal` resolves to the host for local services (e.g., Ollama)
- **SSH agent:** if your shell has `SSH_AUTH_SOCK` set, `c0 start` forwards it automatically. On macOS Docker VM contexts such as OrbStack, the relay `/run/host-services/ssh-auth.sock` is mounted directly at `/home/dev/.ssh-auth.sock`, which is also the in-container `SSH_AUTH_SOCK`; the SSH compose overlay adds the socket group so the dev user can connect without a proxy. If your Docker VM uses a nonstandard socket group, set `C0_SSH_AUTH_SOCK_GID`. Verify with `c0 status` or, inside the container, `test -S "$SSH_AUTH_SOCK" && ssh-add -l`.

## Troubleshooting
- First-run checks: run `c0 doctor --fix`
- Docker failures: `c0` auto-starts OrbStack on macOS when the Docker endpoint is OrbStack and the daemon is unavailable. Set `C0_DOCKER_AUTOSTART=0` to disable.
- SSH agent unavailable: confirm `SSH_AUTH_SOCK` is set in the host shell, restart (`c0 restart`), then run `c0 status` to confirm the container agent is reachable.
- Build failures: confirm Xcode is available for `infocmp`, rerun with `c0 build -f` to force rebuild
- Volume issues: repo-local directories are created automatically; missing host files still require explicit user action

## Debug: Tools Garbage Collection

The c0dev tool implements automatic garbage collection for shared tools volume hashes to prevent unbounded growth while maintaining safety for running containers.

### Key Concepts

**Active Hashes**: Tool hashes currently used by running containers (detected via container labels). Never deleted.

**Pinned Hashes**: Each folder's "latest successful build" hash, stored in `/tools/pins/<folder-id>.pin` within the shared volume. Persists until:
- `c0 clean` is run in that folder
- The folder is deleted from disk (becomes orphaned)
- A new successful `c0 build` updates the pin

**Garbage Collection**: Automatically removes hash directories from `/tools/opt/<hash>/` that are neither active nor pinned. Triggered only on:
- Successful `c0 build` completion
- `c0 clean` execution

### Staged Rebuilds

When forcing a rebuild (`c0 build -f`) of a hash currently active in running containers:
- Tools are built and staged to `/tools/tmp/<hash>.next` instead of `/tools/opt/<hash>`
- Promotion to `/tools/opt/<hash>` happens automatically when no instances use that hash
- Promotion is checked at the start of `c0 build` and `c0 clean`

### Inspecting State

View active hashes from running containers:
```bash
# List running container IDs using tools volume
docker ps -q --filter "volume=c0dev-tools-shared"

# Check hash label from a container
docker inspect <container-id> --format '{{ index .Config.Labels "c0dev.tools_hash" }}'
```

View pinned hashes in shared volume:
```bash
# List all pins
docker run --rm -v c0dev-tools-shared:/tools alpine ls -la /tools/pins

# Read a specific pin
docker run --rm -v c0dev-tools-shared:/tools alpine cat /tools/pins/<folder-id>.pin
```

View hash directories:
```bash
# List tool hash directories
docker run --rm -v c0dev-tools-shared:/tools alpine ls -la /tools/opt

# List staged .next builds
docker run --rm -v c0dev-tools-shared:/tools alpine ls -la /tools/tmp
```

### Safety Guarantees

- **Never deletes active hashes**: Running containers always protected
- **Never modifies pins from containers**: Pin operations are host-only
- **Never promotes staged builds while active**: Waits for instances to stop
- **Never triggers GC on build failure**: Only successful builds clean up
- **Never updates pins on build failure**: Pins represent last known good state
- **Atomic operations**: Uses `.partial` → rename pattern for all promotions
