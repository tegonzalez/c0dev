# c0dev

A containerized development environment for AI-assisted coding and full-stack work, packaged as a reproducible Docker image with modern CLI tooling.

## Overview

**Purpose:** Run a reproducible Linux dev environment in Docker with preinstalled assistant CLIs, polyglot toolchains, and host-persisted credentials and projects.

**Audience:** Developers on macOS who want an isolated workspace for autonomous coding agents and full-stack work without reconfiguring the host shell.

**In scope:** Building and running the c0dev container, mounting host data into the guest, inbound loopback SSH, and operational commands via `c0`.

**Non-goals:** Multi-tenant isolation, production deployment, or sandboxing agents from your own mounted data and credentials.

## Terms

| Term            | Meaning |
| --------------- | ------- |
| checkout        | Your clone of this repository on the host |
| guest           | The running c0dev container |
| dev user        | Default shell user inside the guest (`uid` 1000); use `c0 sh` |
| `TOOLS_ID`      | Content hash of `docker/Dockerfile.base` + `docker/Dockerfile.tools`; selects the immutable toolchain directory on the shared tools volume |
| tools volume    | Docker volume `c0dev-tools-shared` (override: `SHARED_TOOLS_VOLUME`); holds `/tools/opt/<TOOLS_ID>/` |
| instance        | Per-checkout container identity (`c0dev.instance` label); ports and hostname are allocated per instance |

## Host requirements

**Status (fact):** Alpha — validated on the author's workstation only.

| Requirement | Version or note |
| ----------- | --------------- |
| macOS       | Apple M-series, Tahoe v26.5 |
| OrbStack    | orbctl 2.2.1 (2020100) |
| Terminal    | Ghostty v1.3.1 |
| Xcode       | Required for `infocmp` during image build |

## Image summary

| Property    | Value                                                 |
| ----------- | ----------------------------------------------------- |
| Base distro | Debian (downstream of `oven/bun:latest`)              |
| Image size  | ~4 GB total                                           |
| Build time  | ~20 minutes for a full build including Rust toolchain |

## Tooling inventory

### Built from source (Cargo)

| Tool          | Version | Role |
| ------------- | ------- | ---- |
| `fd`          | 10.3.0  | Fast file finder |
| `ripgrep`     | 14.1.1  | Recursive search |
| `ast-grep`    | 0.39.4  | Structural code search |
| `zellij`      | 0.43.1  | Terminal multiplexer |
| `cargo-cache` | —       | Cargo cache management |

### Installed via package managers

- Python: `uv`, `code-graph-rag` (commit 0037ad4)
- Bun globals: `@anthropic-ai/claude-code`, `@openai/codex`, `opencode-ai`
- System utilities: `build-essential`, `cmake`, `git`, `curl`, `wget`, `fzf`, `jq`, `yq`, `bc`, `bat`, `btop`, `iproute2`, `iputils-ping`, `net-tools`, `socat`, `netcat`, `vim`, `tmux`
- Rust toolchain: `rustup` with `wasm32-unknown-unknown` target (registry cache cleaned post-build)

## Quick start

1. Clone: `git clone https://github.com/tegonzalez/c0dev.git`
1. Enter the checkout: `cd c0dev`
1. Load helper scripts: `./env.sh`
1. Build the image: `c0 build` (~10 minutes on first run)
1. Start services: `c0 start`
1. Open a shell: `c0 sh` (auto-navigates to a matching project directory under `projects/`)

```bash
git clone https://github.com/tegonzalez/c0dev.git
cd c0dev
./env.sh
c0 build
c0 start
c0 sh
```

## Usage

### Service management

```bash
c0 start                  # Start the development environment
c0 sh                     # Shell as dev user (UID 1000)
c0 root                   # Shell as root (UID 0); prefer over sudo
c0 stop                   # Stop all services
c0 restart                # Restart services
c0 logs                   # Show logs
c0 status                 # Service status, volume mappings, workspaces
c0 build [-f]             # Build tools and image (-f forces tools re-extract)
c0 ssh                    # SSH as dev (loopback only; keys in auth/ssh/)
c0 ssh --keygen           # Regenerate auth/ssh keys
```

Use `c0 sh` or `c0 ssh` for interactive shells. The container daemon keeps running in the background (`docker attach` does not open a shell).

### Web port mapping

- Guest listens on port `3000`. The host port is auto-selected per checkout.
- Range: `3000–4000`. Rule: first available port in the range (fills gaps).
- Mapping is printed on `c0 start`, `c0 restart`, and `c0 status` as `host:<port> -> guest:3000`.
- Override: `C0DEV_WEB_PORT=3001 c0 start`

### Inbound SSH (loopback)

- Guest `sshd` listens on port `2222`; the host publishes **`127.0.0.1:<port>` only** (not LAN-wide).
- Range: `2222–2322` (same gap-fill rule as web ports). Shown on `c0 start`, `c0 restart`, and `c0 status`.
- Keys and host key live under gitignored `auth/ssh/` (created on first `c0 start` or `c0 build`). Pubkey auth only.
- Connect: `c0 ssh` (same project-path behavior as `c0 sh`). Override: `C0DEV_SSH_PORT=2223 c0 start`.

## Authenticate assistants

### Claude Code

1. Run `claude setup-token` inside the guest.
1. Follow the browser prompt (Ghostty: CMD+click the URL) and approve long-term access. From host: `open $(pbpaste 2>/dev/null | tr -d '\n' || echo '(paste URL)')`
1. Confirm the token is stored under `/home/dev/.claude.json` (persisted via the host volume).

### Codex CLI

Run `codex login --device-auth` inside the guest and follow the prompts.

### OpenCode CLI

1. Run `opencode auth login` inside the guest.
1. Choose your provider (or supply a URL) and finish the browser flow.
1. Credentials are saved under `/home/dev/.config/opencode` for reuse.

## Volume mappings

Persistent host ↔ guest paths for credentials, tooling, and projects:

| Host path        | Guest path              | Role |
| ---------------- | ----------------------- | ---- |
| `.claude/`       | `/home/dev/.claude`     | Assistant state |
| `.cache/`        | `/home/dev/.cache`      | Mutable tool caches (cargo registry, uv); `c0` never purges |
| `.config/`       | `/home/dev/.config`     | Application config |
| `.codex/`        | `/home/dev/.codex`      | Assistant state |
| `rules/`         | `/home/dev/rules`       | Project rules |
| `projects/`      | `/home/dev/projects`    | Sources and build outputs |
| `bin/`           | `/home/dev/bin`         | Host helper scripts |
| `auth/ssh/`      | `/home/dev/.ssh`        | SSH keys and `sshd` config (gitignored) |
| `.claude.json`   | `/home/dev/.claude.json`| Assistant credentials file |
| `tools-shared`   | `/tools:ro`             | Immutable toolchains (rustup, cargo bins, uv tools) |

Immutable Rust and uv binaries live on the read-only tools volume. Download caches live under host `.cache/` (`CARGO_HOME=~/.cache/cargo`, `UV_CACHE_DIR=~/.cache/uv`). After a toolchain upgrade, purge incompatible cache manually (for example `rm -rf .cache/cargo`).

## Environment defaults

| Setting        | Default |
| -------------- | ------- |
| Locale         | `en_US.UTF-8` |
| Timezone       | `America/Los_Angeles` (`TZ` build arg overrides) |
| Web port       | `host:<auto> -> guest:3000` (range `3000–4000`; override `C0DEV_WEB_PORT`) |
| SSH port       | `127.0.0.1:<auto> -> guest:2222` (range `2222–2322`; override `C0DEV_SSH_PORT`) |
| LLM provider   | Ollama at `http://host.docker.internal:11434` |
| Default model  | `gpt-oss:20b` |

## Build pipeline

On `c0 build`:

1. Ensures host mount directories exist (prevents Docker from creating them as root-owned paths).
1. Builds `tools-builder` from `docker/Dockerfile.base` + `docker/Dockerfile.tools` via `bin/dockerfile-concat` (OrbStack-compatible; no BuildKit include).
1. Extracts immutable tool artifacts to the shared tools volume at `/tools/opt/<TOOLS_ID>/`.
1. Builds the runtime image from `docker/Dockerfile.base` + `docker/Dockerfile.runtime` (concatenated the same way).
1. Installs terminfo for proper terminal emulation.

**`TOOLS_ID` computation:** `bin/docker-hash docker/Dockerfile.base docker/Dockerfile.tools` (full-line comments stripped).

**Invalidation (decision):** Changes to `Dockerfile.runtime` alone rebuild the runtime image only; they do not invalidate tools. Run `c0 build` without `-f` for image-only rebuilds. Run `c0 build -f` to force tools re-extract.

Each successful build pins the checkout's `TOOLS_ID` in the tools volume for garbage-collection metadata. Running containers are never deleted by GC.

## Networking

- The guest has outbound network access with host bridging.
- `host.docker.internal` resolves to the host for local services (for example Ollama).
- **SSH agent:** host `ssh-add -l` must work (1Password SSH agent or launchd). `c0` never bind-mounts host `$SSH_AUTH_SOCK`; it mounts the OrbStack/Desktop relay **`/run/host-services/ssh-auth.sock`** at the **same path** in the guest (`SSH_AUTH_SOCK=/run/host-services/ssh-auth.sock`). Required for 1Password. Verify in the guest: `echo $SSH_AUTH_SOCK` and `ssh-add -l`. Disable: `C0_SSH_AGENT=0`.

## Security

c0dev is a **single-user local development container**, not a multi-tenant sandbox. It is designed to run **autonomous coding agents** — tools that can execute shell commands, edit files, and reach the network with minimal human approval. The security model is: **contain blast radius on your workstation**, not **prevent a trusted agent from doing its job**.

### Threat model

| Boundary   | Scope |
| ---------- | ----- |
| In scope   | Compromised or misbehaving agent inside the guest; accidental credential exposure; limiting what a container escape or Docker misconfiguration could leverage on the host |
| Out of scope | Operator who already controls the checkout, Docker daemon, or macOS user account |
| Assumption | One human owns the host, the checkout, and all mounted guest paths (`projects/`, assistant config dirs, `auth/ssh/`, host `~/.gitconfig`, etc.) |

### Capability handling

Runtime containers are **not privileged**. On `c0 start`, compose applies the security overlay (`docker-compose.security-permissive.yaml`):

| Control              | Setting |
| -------------------- | ------- |
| Privileged           | `false` |
| Capabilities         | `cap_drop: ALL`, then add `DAC_OVERRIDE`, `CHOWN`, `FOWNER` |
| Privilege escalation | `no-new-privileges:true` |
| Syscalls             | Moby default seccomp profile (vendored under `docker/seccomp/`, checksum-verified at start/build) |

`DAC_OVERRIDE`, `CHOWN`, and `FOWNER` let `c0 root` and package installs work inside the guest without running `sshd` setuid or granting broad Linux capabilities. They are **guest-admin helpers**, not host-root equivalents.

`sshd` listens on guest port `2222` and runs as the `dev` user (no setuid). The host publishes **`127.0.0.1:<port>` only**.

Ephemeral `docker run` invocations during `c0 build` also use `cap_drop: ALL` and `no-new-privileges`.

### Hardening in place

| Control            | Mechanism |
| ------------------ | --------- |
| Immutable toolchains | `tools-shared` mounted read-only at `/tools:ro`; caches in host `.cache/` |
| Loopback SSH       | Pubkey-only inbound login; keys in gitignored `auth/ssh/` |
| SSH agent relay    | Guest uses OrbStack `/run/host-services/ssh-auth.sock` relay (1Password-safe), not a raw bind of host `$SSH_AUTH_SOCK` |
| Seccomp integrity  | Tampered or missing vendored profiles block `c0 start` / `c0 build`; run `c0 seccomp-upgrade` to adopt newer Moby profiles deliberately |

### Autonomous agents

**Benefits of running agents in the guest**

| Benefit                      | Effect |
| ---------------------------- | ------ |
| Process isolation            | Agent shells, servers, and crashes stay out of the host shell environment |
| Capability + seccomp baseline | Drops Linux caps and restricts syscalls vs a bare host shell |
| Immutable `/tools`           | Reduces in-session tampering of prebuilt CLIs |
| Scoped networking defaults   | Web and SSH ports are explicit; SSH is loopback-only |
| Reproducible toolchain       | Same Rust, uv, and assistant CLIs across machines and rebuilds |

**Residual agent authority (by design)**

Agents run as `dev` (`uid` 1000) with passwordless `c0 root` available. With network egress and bind mounts, they can:

- Read and write everything under `projects/`, assistant config dirs, `.config/`, `rules/`, and `bin/`
- Use mounted credentials (API tokens, `~/.gitconfig`, SSH keys in `auth/ssh/`)
- Use any key currently loaded in the host SSH agent
- Reach the public internet and `host.docker.internal`
- Run arbitrary code inside the guest, including as root via `c0 root`

c0dev does not sandbox agents from *your* data; it sandboxes them from *other host processes* and applies a consistent cap/seccomp floor.

**Operational guidance**

- Treat the guest like a **powerful local shell**, not an untrusted multi-tenant VM.
- Keep secrets in gitignored paths; never commit `auth/ssh/` or assistant token files.
- Use a dedicated checkout and `projects/` tree for untrusted repos.
- Disable SSH agent forwarding when not needed: `C0_SSH_AGENT=0`.
- For secretless or brokered API access, see `c0-aegis`.

### Residual risks

| Risk                     | Note |
| ------------------------ | ---- |
| Bind-mounted entrypoint  | `docker-entrypoint.sh` is mounted from the checkout; the same user who runs agents controls startup |
| Docker group             | Docker daemon access can inspect volumes, override compose, or run privileged containers outside c0dev's profile |
| Agent + SSH agent        | A compromised session can use any key loaded in the host agent until removed |
| Build staging permissions | Tools builds briefly use permissive permissions under `/tools/tmp/` on the shared volume; concurrent Docker-level access could race during build |

### Optional hardening

- Restrict `sshd` with `ListenAddress` / `AllowUsers` in guest `sshd_config`
- Validate `C0_SSH_AUTH_BIND` before writing generated compose fragments
- Tighten build-time permissions on `/tools/tmp/<id>.partial`
- Add a stricter cap profile for read-mostly agent sessions (for example drop `DAC_OVERRIDE` / `FOWNER`)

## Troubleshooting

- Build failures: confirm Xcode is available for `infocmp`; rerun with `c0 build -f` to force rebuild.
- Volume issues: ensure host directories exist and remain writable before `c0 build`.
- Empty or stale tools after layout changes: run `c0 build` once to populate `/tools/opt/<TOOLS_ID>/`, then `c0 restart`.
- Container label `c0dev.instance` identifies the checkout instance.

## Tools garbage collection

Automatic garbage collection for shared tools volume **`TOOLS_ID`** directories prevents unbounded growth while protecting running containers.

### Concepts

| Concept            | Definition |
| ------------------ | ---------- |
| Active `TOOLS_ID`  | Value used by a running container (`c0dev.tools_hash` label); never deleted |
| Pinned `TOOLS_ID`  | Latest successful build for a checkout, stored in `/tools/pins/<folder-id>.pin`; updated on successful `c0 build`, cleared by `c0 clean` or checkout deletion |
| Garbage collection | Removes `/tools/opt/<tools_id>/` directories that are neither active nor pinned; runs after successful `c0 build` or `c0 clean` |

### Staged rebuilds

When forcing a rebuild (`c0 build -f`) of a `TOOLS_ID` currently used by running containers:

- Tools build to `/tools/tmp/<tools_id>.next` instead of `/tools/opt/<tools_id>`
- Promotion to `/tools/opt/<tools_id>` happens when no instance uses that `TOOLS_ID`
- Promotion is checked at the start of `c0 build` and `c0 clean`

### Inspecting state

Active `TOOLS_ID` from running containers:

```bash
docker ps -q --filter "volume=c0dev-tools-shared"
docker inspect <container-id> --format '{{ index .Config.Labels "c0dev.tools_hash" }}'
```

Pinned `TOOLS_ID` values:

```bash
docker run --rm -v c0dev-tools-shared:/tools alpine ls -la /tools/pins
docker run --rm -v c0dev-tools-shared:/tools alpine cat /tools/pins/<folder-id>.pin
```

`TOOLS_ID` directories:

```bash
docker run --rm -v c0dev-tools-shared:/tools alpine ls -la /tools/opt
docker run --rm -v c0dev-tools-shared:/tools alpine ls -la /tools/tmp
```

### Safety guarantees

- Never deletes active `TOOLS_ID` values used by running containers
- Never modifies pins from inside the guest
- Never promotes staged builds while an instance still uses the `TOOLS_ID`
- Never triggers GC on build failure
- Never updates pins on build failure
- Uses `.partial` → rename for atomic promotions
