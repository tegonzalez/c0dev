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
- Python: `uv`, `code-graph-rag` (commit 0037ad4)
- Bun globals: `@anthropic-ai/claude-code`, `@openai/codex`, `opencode-ai`
- System utilities: `build-essential`, `cmake`, `git`, `curl`, `wget`, `fzf`, `jq`, `yq`, `bc`, `bat`, `btop`, `iproute2`, `iputils-ping`, `net-tools`, `socat`, `netcat`, `vim`, `tmux`
- Rust toolchain: `rustup` with `wasm32-unknown-unknown` target (registry cache cleaned post-build)

## Quick Start Workflow
### Bootstrap the Workspace
1. Clone the repo: `git clone https://github.com/tegonzalez/c0dev.git`
2. Enter the project: `cd c0dev`
3. Load helper scripts into `PATH`: `./env.sh`
4. Build the image: `c0 build` (first build takes ~10 minutes)

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

# Build the Docker image (~10 minutes)
c0 build
```

**Build Time**: Approximately 10 minutes for full build including Rust toolchain installation.

### What `c0 build` Does
1. Ensures file mappings exist on host (prevents Docker from creating directories)
2. Builds `tools-builder` stage with uv, Cursor CLI, code-graph-rag, and Rust tools
3. Extracts built tools to host directories (`.local`, `.cargo`, `.rustup`)
4. Builds final Docker image with system packages and global tools
5. Installs terminfo for proper terminal emulation

## Usage

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
```

## Authenticate Assistants

### Claude Code
1. Run `claude setup-token` inside the container.
2. Follow the browser prompt (Ghostty users can CMD+click the URL) and approve long-term access.
3. Wait for the CLI to confirm the token was stored under `/home/dev/.claude.json` (persisted via the host volume).

### Codex CLI
1. Start the local redirect listener: `c0 codex-auth` (keeps port 1455 open while you log in).
2. In a separate terminal, run `codex login` and complete the web-based OAuth flow.
3. After the CLI reports success, return to the first terminal and press `Ctrl+C` to stop `c0 codex-auth`.

### OpenCode CLI
1. Run `opencode auth login` to start the interactive login.
2. Choose your provider (or supply a URL) and finish the browser flow when prompted.
3. The CLI saves credentials under `/home/dev/.config/opencode`, so future sessions reuse the same login.

## Volume Mappings
Persistent host ↔ container paths for credentials, tooling, and projects:
- `.claude/` → `/home/dev/.claude`
- `.config/` → `/home/dev/.config`
- `.cargo/` → `/home/dev/.cargo`
- `.local/` → `/home/dev/.local`
- `.rustup/` → `/home/dev/.rustup`
- `.terminfo/` → `/home/dev/.terminfo`
- `rules/` → `/home/dev/rules`
- `projects/` → `/home/dev/projects`
- `bin/` → `/home/dev/bin`
- `.claude.json` → `/home/dev/.claude.json`

These mappings keep credentials, tool installs, and in-progress work outside the ephemeral container filesystem.

## Environment Defaults
- Locale: `en_US.UTF-8`
- Timezone: `America/Los_Angeles` (`TZ` build arg overrides)
- Exposed ports: `1455` (Codex auth), `3000` (general dev server)
- LLM provider: Ollama at `http://host.docker.internal:11434`
- Default model: `gpt-oss:20b`

## Build Pipeline Highlights
1. Verify host directories exist before mounting volumes
2. Build `tools-builder` stage (uv, Cursor CLI, code-graph-rag, Rust tools)
3. Extract tool artifacts to host (`.local`, `.cargo`, `.rustup`)
4. Assemble final runtime image with system packages and global CLIs
5. Install terminfo database for accurate terminal emulation

## Networking Notes
- Container has public network access with host bridging
- `host.docker.internal` resolves to the host for local services (e.g., Ollama)

## Troubleshooting
- Build failures: confirm Xcode is available for `infocmp`, rerun with `c0 build -f` to force rebuild
- Volume issues: ensure host directories exist and remain writable before running `c0 build`
