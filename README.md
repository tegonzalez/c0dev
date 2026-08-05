---
doc-graph: "When there is an intention to amend this document, first Adhere to [dc-doc-readme]; otherwise, do not modify."
---

# c0dev

A containerized development environment for AI-assisted coding and full-stack work, packaged as a reproducible Docker image with modern CLI tooling.

## Overview

**Purpose:** Run a reproducible Linux dev environment in Docker with preinstalled assistant CLIs, polyglot toolchains, and host-persisted credentials and projects.

**Audience:** Developers on macOS who want an isolated workspace for autonomous coding agents and full-stack work without reconfiguring the host shell.

**In scope:** Building and running the c0dev container, mounting host data into the guest, inbound loopback SSH, and operational commands via `c0`.

**Non-goals:** Multi-tenant isolation, production deployment, or sandboxing agents from your own mounted data and credentials.

Documentation questions route through the [c0dev authority index](docs/index.md). README is an onboarding summary, not the owner of detailed behavior or architecture.

### Command-oriented architecture

```text
CONTAINER LIFETIMES

                                               +-----------+
c0 build [-f]  +-------------- install ------->|   tools   |
               |                               +-----+-----+
               |                                     |
               |                                     X
                                               +-----------+
               +--------------- image -------->|   build   |
                                               +-----+-----+
                                                     |
                                                     X


                                                               +-----------+
c0 start/restart  +------------------- lifecycle ------------->|  runtime  |
                  |                                            +-----+-----+
                  |                                                  |
                                         +-----------+               |
                  +------- create ------>|  overlay  |               |
                                         +-----+-----+               |
                                               +---- mount --------->|
                                               X                     |
                                                                     |
c0 sh/ssh      |------------------------- dev exec ----------------->|
                                                                     |
                                                                     |
c0 root        |------------------------- uid 0 exec --------------->|
                                                                     |
                                                                     |
c0 status      |------------------------- inspect ------------------>|
                                                                     |
                                                                     |
c0 stop        |---------------------------- stop ------------------>X


PERSISTENT STORAGE ACCESS

                           +-----------+
                           |   tools   |------ RW ---------+
                           +-----+-----+                   |
                                                           |
                                                           |      /-------------\
                           +-----------+                   |     /              \
                           |  overlay  |------ RO lower ---+---->| tools-volume |
                           +-----+-----+                   |     \              /
                                                           |      \-------------/
 /-------------\                                           |
/              \           +-----------+                   |
|  host-mount  |--- RW --->|  runtime  |------ RO ---------+
\              /           +-----+-----+                   |
 \-------------/                                           |
                                                           |
c0 status      |----------------- RO inspect --------------+
                                                           |
c0 clean       |----------------- GC ----------------------+
```

#### `build`

- Type: Guest instance used for runtime-image construction.
- Lifetime: Bounded by the runtime-image phase of `c0 build`; exits afterward.
- User: Root for apt and image setup; the resulting runtime image switches to `dev`.
- Security: Docker/BuildKit build profile.
- Network: Build network for apt and package retrieval.
- Storage: Writes image layers only.
- Use: Produces the image consumed by a later runtime create or restart.

#### `tools`

- Type: Guest instance used for tool installation and extraction.
- Lifetime: Bounded by the tools phase of `c0 build`; exits afterward.
- User: `dev` for uv, Cursor, Droid, Devin, Semgrep, Rustup, and Cargo installers.
- Security: Extraction runs with dropped capabilities and NNP; the tools-builder stage starts after `USER dev`.
- Network: Build network for vendor and package downloads.
- Storage: Writes `tools-volume` only during construction and extraction.
- Use: Populates the shared canonical tool payload.

#### `overlay`

- Type: Short-lived guest instance used for the current writable-`.local` compatibility mount.
- Lifetime: Created during start or restart when the runtime overlay is absent; exits after mounting.
- User: UID 0.
- Security: `SYS_ADMIN`, `SYS_PTRACE`, `SYS_CHROOT`, DAC/ownership capabilities, NNP, and unconfined seccomp.
- Network: None.
- Storage: Reads the selected tools lower and writes the per-instance overlay-stage volume while entering the runtime mount namespace.
- Use: Mounts writable `.local` into `runtime`; the helper exits immediately after the mount succeeds.

#### `runtime`

- Type: Long-running development guest instance.
- Lifetime: Starts or recreates through `c0 start` or `c0 restart`; ends through stop or recreation.
- User: `dev`; `c0 root` enters UID 0 inside the same instance.
- Security: `cap_drop: ALL`, then `CHOWN`, `DAC_OVERRIDE`, `FOWNER`; NNP; vendored Moby seccomp.
- Network: Normal guest egress with loopback-published web and SSH ports.
- Storage: Reads only its selected tools-volume subpath RO and writes host mounts, its overlay stage, and the runtime layer.
- Use: Runs shells, agents, services, and apt administration.

#### `tools-volume`

- Type: Persistent Docker volume.
- Lifetime: Independent of every guest instance.
- User: Access depends on the operating guest or host volume operation.
- Security: Only the selected `/tools/opt/<TOOLS_ID>` subpath is mounted read-only in `runtime`.
- Network: Not applicable.
- Storage: Written during build or explicit stage acceptance and eligible cleanup; inspected read-only by status.
- Use: Stores immutable build toolsets, accepted snapshots, pins, and temporary publication paths.

#### `host-mount`

- Type: Persistent host bind set.
- Lifetime: Independent of every guest instance.
- User: Host ownership mapped for `dev` access in `runtime`.
- Security: Ordinary bind-mount permissions; contents are deliberately guest-writable.
- Network: Not applicable.
- Storage: Config, auth, cache, logs, XDG state, projects, rules, and credentials.
- Use: Preserves user state across runtime stop, restart, and recreation.

Not shown as nodes: `c0 root` is an exec lane inside `runtime`; `c0 tools accept` briefly pauses and recreates `runtime` while using the existing overlay-helper class plus a separate networkless publisher; `tools-volume-helper` is an unnamed one-operation `--rm` process; SSH relay, logs, `cp-term`, seccomp update, and key generation are implementation or maintenance details.

## Terms

| Term              | Meaning                                                                                                                                  |
| ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| checkout          | Your clone of this repository on the host                                                                                                |
| guest             | The running c0dev container                                                                                                              |
| dev user          | Default shell user inside the guest (`uid` 1000); use `c0 sh`                                                                            |
| `TOOLS_BUILD_ID`  | Content hash of `Dockerfile.base` and `Dockerfile.tools`; identifies the build-produced toolset                                          |
| `TOOLS_ID`        | Complete build toolset or accepted-stage snapshot selected for one checkout                                                              |
| tools volume      | Docker volume `c0dev-tools-shared` (override: `SHARED_TOOLS_VOLUME`); holds immutable `/tools/opt/<TOOLS_ID>/` snapshots                 |
| writable stage    | Per-instance OverlayFS upper containing every runtime write beneath the overlaid tool-home paths                                         |
| instance          | Per-checkout container identity (`c0dev.instance` label); ports and hostname are allocated per instance                                  |

## Host requirements

**Status (fact):** Alpha — validated on the author's workstation only.

| Requirement | Version or note                           |
| ----------- | ----------------------------------------- |
| macOS       | Apple M-series, Tahoe v26.6.2             |
| OrbStack    | orbctl 2.2.3 (20963)                      |
| Terminal    | Ghostty v1.3.1                            |
| Xcode       | Required for `infocmp` during image build |

## Image summary

| Property    | Value                                                 |
| ----------- | ----------------------------------------------------- |
| Base distro | Debian (downstream of `oven/bun:latest`)              |
| Image size  | ~4 GB total                                           |
| Build time  | ~20 minutes for a full build including Rust toolchain |

## Tooling inventory

### Built from source (Cargo)

| Tool          | Role                   |
| ------------- | ---------------------- |
| `fd`          | Fast file finder       |
| `rg`          | Recursive search       |
| `ast-grep`    | Structural code search |
| `zellij`      | Terminal multiplexer   |
| `nu`          | Structured shell       |
| `cargo-cache` | Cargo cache management |

### Installed via package managers

- Standalone/tool managers: `uv`, `uvx`, Cursor Agent, Factory Droid, Devin CLI, Semgrep
- Bun globals: `@anthropic-ai/claude-code`, `@openai/codex`, `opencode-ai`, `@kaitranntt/ccs`
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
c0 tools                  # Summarize the writable tools stage
c0 tools --detail         # List every staged path
c0 tools accept           # Seal the stage as a new immutable snapshot
c0 tools restore          # Discard the stage and restore the selected snapshot
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

`claude setup-token`

### Codex CLI

`codex login --device-auth`

### Devin CLI

`devin setup`

### OpenCode CLI

`opencode auth login`

## Volume mappings

Persistent host ↔ guest paths for credentials, tooling, and projects: see `./docker/volumes-folders.yaml`, eg:

| Host path      | Guest path               | Role                                                           |
| -------------- | ------------------------ | -------------------------------------------------------------- |
| `.claude/`     | `/home/dev/.claude`      | Assistant state                                                |
| `.cache/`      | `/home/dev/.cache`       | Mutable tool caches (cargo registry, uv); `c0` never purges    |
| `.config/`     | `/home/dev/.config`      | Application config                                             |
| `.codex/`      | `/home/dev/.codex`       | Assistant state                                                |
| `.local/`      | `/home/dev/.local-rw`    | Host-visible XDG data and state                                |
| `rules/`       | `/home/dev/rules`        | Project rules                                                  |
| `projects/`    | `/home/dev/projects`     | Sources and build outputs                                      |
| `bin/`         | `/home/dev/bin:ro`       | Read-only host router and guest-safe helper scripts            |
| `auth/ssh/`    | `/home/dev/.ssh`         | SSH keys and `sshd` config (gitignored)                        |
| `.claude.json` | `/home/dev/.claude.json` | Assistant credentials file                                     |
| `tools-shared` | `/tools/current:ro`      | Only this checkout's selected immutable tool snapshot          |
| `home-overlays`| `/run/c0/overlay-state`  | Per-instance writable tool stage and OverlayFS work data       |

Canonical executables and resources come from the selected read-only tools snapshot. Native writes beneath an overlaid tool-home path enter the per-instance writable stage. XDG data/state is redirected to the host `.local/`; direct writers that ignore XDG remain part of the stage and are therefore included by `c0 tools accept` or removed by `c0 tools restore`.

`PATH` resolves `.local` tools through merged `/home/dev/.local/bin`, so a staged native upgrade is effective immediately while the selected lower remains unchanged.

## Environment defaults

| Setting       | Default                                                                         |
| ------------- | ------------------------------------------------------------------------------- |
| Locale        | `en_US.UTF-8`                                                                   |
| Timezone      | `America/Los_Angeles` (`TZ` build arg overrides)                                |
| Web port      | `host:<auto> -> guest:3000` (range `3000–4000`; override `C0DEV_WEB_PORT`)      |
| SSH port      | `127.0.0.1:<auto> -> guest:2222` (range `2222–2322`; override `C0DEV_SSH_PORT`) |
| LLM provider  | Ollama at `http://host.docker.internal:11434`                                   |
| Default model | `gpt-oss:20b`                                                                   |

## Build pipeline

On `c0 build`:

1. Ensures host mount directories exist (prevents Docker from creating them as root-owned paths).
1. Builds the runtime image from `docker/Dockerfile.base` + `docker/Dockerfile.runtime` (concatenated the same way).
1. Builds the UID-1000 tools-builder stage from the supported base path.
1. Packs `.cargo/bin`, `.rustup`, and the complete builder-created `.local` tree.
1. Extracts the payload through a temporary path and writes the completeness marker last.
1. Pins the completed build toolset for this checkout.
1. Installs terminfo for proper terminal emulation.

`c0 build -f` reruns the same Dockerfile installer path without cache. `c0 tools` is not another build or installer command; it manages writes captured from the running restricted guest.

See the [Tool-store contract](docs/tool-store-contract.md) for exact identity, transaction, publication, rollback, and collection law.

## Networking

- The guest has outbound network access with host bridging.
- `host.docker.internal` resolves to the host for local services (for example Ollama).
- **SSH agent:** host `ssh-add -l` must work (1Password SSH agent or launchd). `c0` bind-mounts OrbStack's VM relay **`/run/host-services/ssh-auth.sock`** at the same guest path and sets `SSH_AUTH_SOCK`; it never mounts the macOS launchd path. Verify with `c0 ssh "ssh-add -l"`. Disable with `C0_SSH_AGENT=0`.

## Security

c0dev is a **single-user local development container**, not a multi-tenant sandbox. It is designed to run **autonomous coding agents** — tools that can execute shell commands, edit files, and reach the network with minimal human approval. The security model is: **contain blast radius on your workstation**, not **prevent a trusted agent from doing its job**.

### Threat model

| Boundary     | Scope                                                                                                                                                                     |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| In scope     | Compromised or misbehaving agent inside the guest; accidental credential exposure; limiting what a container escape or Docker misconfiguration could leverage on the host |
| Out of scope | Operator who already controls the checkout, Docker daemon, or macOS user account                                                                                          |
| Assumption   | One human owns the host, the checkout, and all mounted guest paths (`projects/`, assistant config dirs, `auth/ssh/`, host `~/.gitconfig`, etc.)                           |

### Capability handling

Runtime containers are **not privileged**. On `c0 start`, compose applies the security overlay (`docker-compose.security-permissive.yaml`):

| Control              | Setting                                                                                           |
| -------------------- | ------------------------------------------------------------------------------------------------- |
| Privileged           | `false`                                                                                           |
| Capabilities         | `cap_drop: ALL`, then add `DAC_OVERRIDE`, `CHOWN`, `FOWNER`                                       |
| Privilege escalation | `no-new-privileges:true`                                                                          |
| Syscalls             | Moby default seccomp profile (vendored under `docker/seccomp/`, checksum-verified at start/build) |

`DAC_OVERRIDE`, `CHOWN`, and `FOWNER` let `c0 root` and package installs work inside the guest without running `sshd` setuid or granting broad Linux capabilities. They are **guest-admin helpers**, not host-root equivalents.

`sshd` listens on guest port `2222` and runs as the `dev` user (no setuid). The host publishes **`127.0.0.1:<port>` only**.

Native upgrades run inside the existing restricted runtime and can write only its OverlayFS upper, not the shared tools volume. `c0 tools accept` pauses the runtime for a consistent snapshot, uses the existing networkless namespace helper to read the merged view, and invokes a separate networkless publisher. The publisher creates a new immutable snapshot and selects it for this checkout; it never modifies the selected snapshot in place.

### Hardening in place

| Control                   | Mechanism                                                                                                                                 |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------   |
| Immutable accepted tools  | Runtime mounts only `/tools/opt/<TOOLS_ID>` at `/tools/current:ro`; other shared snapshots are not visible                                |
| Explicit publication      | Runtime writes remain in its upper until the host operator runs `c0 tools accept`; runtime processes never receive volume-write authority |
| Restore boundary          | `c0 tools restore` discards the entire visible upper and recreates the runtime against the selected snapshot                              |
| Loopback SSH              | Pubkey-only inbound login; keys in gitignored `auth/ssh/`                                                                                 |
| SSH agent relay           | OrbStack relay bound at `/run/host-services/ssh-auth.sock`; SSH sessions receive the same guest `SSH_AUTH_SOCK` path                      |
| Seccomp integrity         | Tampered or missing vendored profiles block `c0 start` / `c0 build`; run `c0 seccomp-upgrade` to adopt newer Moby profiles deliberately   |

### Autonomous agents

**Benefits of running agents in the guest**

| Benefit                       | Effect                                                                    |
| ----------------------------- | ------------------------------------------------------------------------- |
| Process isolation             | Agent shells, servers, and crashes stay out of the host shell environment |
| Capability + seccomp baseline | Drops Linux caps and restricts syscalls vs a bare host shell              |
| Immutable `/tools`            | Reduces in-session tampering of prebuilt CLIs                             |
| Scoped networking defaults    | Web and SSH ports are explicit; SSH is loopback-only                      |
| Reproducible toolchain        | Same Rust, uv, and assistant CLIs across machines and rebuilds            |

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

| Risk                     | Note                                                                                                                                             |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| Host orchestrator source | Guest-write exposure of host `c0`, publisher, adapters, locks, or security profiles would become delayed Docker-authority execution              |
| Docker group             | Docker daemon access can inspect volumes, override compose, or run privileged containers outside c0dev's profile                                 |
| Runtime tool updater     | Fetched updater code can alter the writable stage but cannot publish it or write the shared tools volume without a host-side `accept`            |
| Agent + SSH agent        | A compromised session can use any key loaded in the host agent until removed                                                                     |
| User tool override       | Mutable host tools can shadow effective commands when explicitly selected; they are outside canonical integrity                                  |

### Optional hardening

- Restrict `sshd` with `ListenAddress` / `AllowUsers` in guest `sshd_config`
- Keep host orchestration and publisher source unavailable for guest writes
- Add a stricter cap profile for read-mostly agent sessions (for example drop `DAC_OVERRIDE` / `FOWNER`)

## Troubleshooting

- Build failures: confirm Xcode is available for `infocmp`; rerun with `c0 build -f` to force rebuild.
- Volume issues: ensure host directories exist and remain writable before `c0 build`.
- Inspect tool changes with `c0 tools`; use `--detail` when the added-path summary needs expansion.
- If staged changes are wanted, run `c0 tools accept`; otherwise run `c0 tools restore`. Both commands recreate the runtime.
- A failed accept leaves the previously selected snapshot complete and does not clear the writable stage.
- Container label `c0dev.instance` identifies the checkout instance.

## Tools garbage collection

Build-produced and accepted tool snapshots are immutable. The current checkout pin and running-container labels protect selected snapshots from garbage collection.

### Concepts

| Concept            | Definition                                                                 |
| ------------------ | -------------------------------------------------------------------------- |
| Build toolset      | Immutable payload identified by `TOOLS_BUILD_ID`                           |
| Accepted snapshot  | Immutable merged tool-home snapshot derived from the selected `TOOLS_ID`   |
| Writable stage     | Complete OverlayFS upper reported by `c0 tools`                            |
| Pin                | Per-checkout selection and garbage-collection claim                        |
| Active label       | Running-container claim protecting its selected snapshot                   |
| Garbage collection | Removes complete snapshots protected by neither a valid pin nor active use |

### Stage acceptance

`c0 tools accept` operates on the complete stage shown by `c0 tools --detail`; there are no hidden path exclusions. It pauses the runtime, snapshots each configured merged home overlay, copies the selected immutable snapshot to a new 64-hex path, replaces its overlaid paths with the merged snapshot, records the parent and stage digest, writes `.c0dev-complete` last, and updates the checkout pin. It then clears the upper and recreates the runtime against the accepted snapshot.

`c0 tools restore` recreates the runtime after clearing the same complete upper. It does not change the selected snapshot. Because the entire upper is the stage, direct writers that place logs, credentials, generated bytecode, or configuration beneath the overlay are included in either operation.

### Inspecting state

Current stage:

```bash
c0 tools
c0 tools --detail
```

Pinned `TOOLS_ID` values:

```bash
docker run --rm -v c0dev-tools-shared:/tools alpine ls -la /tools/pins
docker run --rm -v c0dev-tools-shared:/tools alpine cat /tools/pins/<folder-id>.pin
```

Toolset directories:

```bash
docker run --rm -v c0dev-tools-shared:/tools alpine ls -la /tools/opt
docker run --rm -v c0dev-tools-shared:/tools alpine ls -la /tools/tmp
```

### Safety guarantees

- Never gives the runtime guest tools-volume write access
- Never replaces a complete selected snapshot in place
- Never modifies pins from inside the guest
- Never accepts or restores without an explicit host command
- Never triggers GC on build failure
- Never updates pins on build failure
- Writes the accepted snapshot completeness marker last, then updates the checkout pin

See the [Tool-store contract](docs/tool-store-contract.md) for exact state transitions and protection law.
