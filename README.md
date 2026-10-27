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

Run `bash ./env.sh c0 help` for available commands and options; implementations are in `bin/c0` and `docker/`. Every `c0` command in this README is host-side: run it in the child Bash started by `bash ./env.sh`, or prefix a single command with `bash ./env.sh`. The helper changes `PATH` only in its child; exiting it returns to the parent shell. This README is an onboarding summary.

## Features

| Feature              | Purpose                                                                                     |
| -------------------- | ------------------------------------------------------------------------------------------- |
| Reproducible guest   | Build a Linux development container with assistant CLIs and toolchains.                     |
| Persistent workspace | Keep configured credentials, caches, projects, and user state on host mounts.               |
| Per-checkout runtime | Manage an isolated container instance with published web and loopback SSH ports.            |
| Staged tool updates  | Inspect tool changes, accept them as immutable snapshots, or restore the selected snapshot. |
| Runtime restrictions | Apply capability limits, no-new-privileges, and the vendored Moby seccomp profile.          |

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
- Use: Produces the image consumed when a runtime is created.

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
- Lifetime: Created when absent by `c0 start`; stop removes the runtime and retains persistent mounts and volumes. Restart runs stop followed by start.
- User: `dev`; `c0 root` enters UID 0 inside the same instance.
- Security: `cap_drop: ALL`, then `CHOWN`, `DAC_OVERRIDE`, `FOWNER`; NNP; vendored Moby seccomp.
- Network: Normal guest egress with published web and loopback-published SSH ports.
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

Not shown as nodes: `c0 root` is an exec lane inside `runtime`; `c0 tools accept` briefly pauses `runtime` for a tools snapshot using the existing overlay-helper class plus a separate networkless publisher; `tools-volume-helper` is an unnamed one-operation `--rm` process; SSH relay, logs, `cp-term`, seccomp update, and key generation are implementation or maintenance details.

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

Run this in a terminal from a source checkout. The first command starts a child Bash with the checkout's `bin/` directory on `PATH`; it does not change the current shell's `PATH`.

```bash
git clone https://github.com/tegonzalez/c0dev.git
cd c0dev
bash ./env.sh
```

At the helper shell prompt, build and start the runtime, then open the guest shell:

```bash
c0 build
c0 start
c0 sh
```

A successful final command opens the guest shell as `dev` (UID 1000); `c0 sh` auto-navigates to a matching project directory under `projects/`. Exiting the guest shell returns to the helper Bash; exiting the helper returns to the parent shell.

## Commands

| Command | Purpose |
| --- | --- |
| `c0 build [-f]` | Build and validate tools and the runtime image, then publish the checkout selection. |
| `c0 start [--cap-drop-all]` | Resume the existing container; create it only when absent. |
| `c0 stop` | Stop and remove the runtime; retain bind mounts and named volumes. |
| `c0 restart [--cap-drop-all]` | Run stop, then start with the supplied start arguments. |
| `c0 sh` / `c0 root` / `c0 ssh [-Y] [command...]` | Attach as dev, root, or dev over SSH. `ssh --keygen` regenerates SSH keys. |
| `c0 status` / `c0 logs [svc]` | Inspect this instance or view service logs. |
| `c0 tools [--detail\|accept\|restore]` | Inspect, publish, or discard the writable tools stage; see the tools behavior below. |
| `c0 orca [start\|stop\|status]` | Check or manage the guest Orca service. |
| `c0 seccomp-upgrade [--dry-run]` | Check for or apply a newer Moby seccomp profile. |
| `c0 clean [-a]` | Collect unused tools; refuse while any container references the store. |
| `c0 cp-term` | Copy caller terminfo into the guest system terminfo store. |
| `c0 help` | Show command help. |

Run this command table in the host helper Bash started by `bash ./env.sh`. From the parent shell, invoke one command with `bash ./env.sh c0 help`, replacing `help` with the desired command and arguments.

## Usage

Usage recipes below run in the host helper Bash unless they explicitly identify a guest command.

### Service management

```bash
c0 start                  # Start the development environment
c0 sh                     # Shell as dev user (UID 1000)
c0 root                   # Shell as root (UID 0); prefer over sudo
c0 stop                   # Stop all services
c0 restart                # Restart services
c0 logs                   # Show logs
c0 status                 # Service status, volume mappings, workspaces
c0 build                  # Build tools and image
c0 tools                  # Summarize the writable tools stage
c0 tools --detail         # List every staged path
c0 tools accept           # Seal the stage as a new immutable snapshot
c0 tools restore          # Discard the stage and restore the selected snapshot
c0 ssh                    # SSH as dev (loopback only; keys in auth/ssh/)
c0 ssh -Y                 # SSH with trusted X11 forwarding (host X server required)
c0 ssh --keygen           # Regenerate auth/ssh keys
```

Use `c0 build -f` to force tool re-extraction.

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
- Trusted X11: start a host X server, ensure `DISPLAY` is set, then connect with `c0 ssh -Y`. The image includes `xauth`, and c0 enables `X11Forwarding` in its generated guest `sshd_config`.

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

| Host path       | Guest path               | Role                                                                       |
| --------------- | ------------------------ | -------------------------------------------------------------------------- |
| `.claude/`      | `/home/dev/.claude`      | Assistant state                                                            |
| `.cache/`       | `/home/dev/.cache`       | Mutable tool caches (cargo registry, uv); `c0` never purges                |
| `.config/`      | `/home/dev/.config`      | Application config                                                         |
| `.codex/`       | `/home/dev/.codex`       | Assistant state                                                            |
| `.local/`       | `/home/dev/.local-rw`    | Host-visible XDG data and state                                            |
| `rules/`        | `/home/dev/rules`        | Project rules                                                              |
| `projects/`     | `/home/dev/projects`     | Sources and build outputs                                                  |
| `bin/`          | `/run/c0/host-bin:ro`     | Host launcher/helper lower; writable guest view at `/home/dev/bin` uses OverlayFS |
| `auth/ssh/`     | `/home/dev/.ssh`         | SSH keys and `sshd` config (gitignored)                                    |
| `.claude.json`  | `/home/dev/.claude.json` | Assistant credentials file                                                 |
| `~/.gitconfig`  | `/home/dev/.gitconfig:ro` | Host Git identity and settings; guest cannot change the host file          |
| `tools-shared`  | `/tools/current:ro`      | Only this checkout's selected immutable tool snapshot                      |
| `home-overlays` | `/run/c0/overlay-state`  | Per-instance writable tool stage, launcher upper, and OverlayFS work data                   |

The guest `/home/dev/bin` overlays the read-only host `bin/` lower. Guest edits persist in a separate launcher upper across restarts and do not change host scripts. The launcher upper is excluded from `c0 tools accept` and `c0 tools restore`; host updates remain visible for paths the guest has not overridden.

Canonical executables and resources come from the selected read-only tools snapshot. Native writes beneath an overlaid tool-home path enter the per-instance writable stage. XDG data/state is redirected to the host `.local/`; direct writers that ignore XDG remain part of the stage and are therefore included by `c0 tools accept` or removed by `c0 tools restore`.

`PATH` resolves other `.local` tools through merged `/home/dev/.local/bin`, so their staged native upgrades are effective immediately. Core toolchain defaults follow the mounted snapshot manifest. Explicit interpreter paths and per-session `fnm use` remain available.

## Environment defaults

| Setting       | Default                                                                         |
| ------------- | ------------------------------------------------------------------------------- |
| Locale        | `en_US.UTF-8`                                                                   |
| Timezone      | `America/Los_Angeles` (`TZ` build arg overrides)                                |
| Web port      | `host:<auto> -> guest:3000` (range `3000–4000`; override `C0DEV_WEB_PORT`)      |
| SSH port      | `127.0.0.1:<auto> -> guest:2222` (range `2222–2322`; override `C0DEV_SSH_PORT`) |
| LLM provider  | Ollama at `http://host.docker.internal:11434`                                   |
| Default model | `gpt-oss:20b`                                                                   |
| Electron      | `ELECTRON_DISABLE_SANDBOX=1` (required by c0's no-new-privileges isolation)     |

## Build pipeline

On `c0 build`:

1. Ensures host mount directories exist (prevents Docker from creating them as root-owned paths).
1. Resolves current stable toolchain releases once from official upstream metadata, keeping Node on 22 and Python on 3.15; records a canonical manifest before checking the tools cache.
1. Builds or reuses the UID-1000 tools-builder snapshot from the supported base path.
1. Packs `.cargo/bin`, `.rustup`, and the complete builder-created `.local` tree, then extracts through a temporary path and writes the completeness marker last.
1. Prepares terminfo for proper terminal emulation.
1. Builds the runtime image from `docker/Dockerfile.base` + `docker/Dockerfile.runtime`, downloading the pinned Orca 1.4.239 arm64 package, verifying its SHA-256, and installing its headless Electron/Xvfb dependencies.
1. Pins the completed toolset for this checkout only after both tool and runtime builds succeed.

Every `c0 build` resolves the latest stable Bun, uv, fnm, Node 22 patch, Python 3.15 patch, pip, and Semgrep. npm and pnpm select the newest stable versions compatible with the selected Node 22 release. Prereleases, releases below the security floors, malformed metadata, and upstream lookup failures stop the build; failed builds leave the successful checkout selection intact.

The canonical manifest and Dockerfile recipe together determine the tools snapshot identity. A new resolved release invalidates the old snapshot even when the Dockerfiles are unchanged. Unchanged manifests can reuse complete snapshots. A build publishes the image and tools selection for container creation. The running container keeps its fixed image and tools mount until stopped. After `c0 stop`, `c0 start` creates from the published image and selected tools. The exact versions are passed to both image builds and verified during installation; the manifest is retained in `/tools/current/.c0dev-toolchain.json` and `/tools/current/.local/share/c0/toolchain.json` for inspection.

`c0 build -f` also pulls the selected base and bypasses Docker layer caching. Ordinary image builds use `--pull`. This release resolver is not a CVE scanner: same-version distro package changes, independently vendored application runtimes, Rust transitive changes, and existing project environments still need their own security review or a forced rebuild.

Normal `c0 sh` and `c0 ssh` select the mounted snapshot's Node/Python, package-manager and uv defaults, even when a persistent home overlay contains older generic launchers or fnm defaults. Selection uses private cache shims without deleting staged files or rewriting custom fnm aliases. Node/Python versions remain available for explicit per-session selection. Login, status, start, and SSH do not resolve toolchain releases or install tools; only `c0 build` contacts release services.

Debian's `/usr/bin/python3` remains available for system-package shebangs and dependencies; replacing or removing it would break those consumers. Existing project virtual environments keep their own interpreter and packages. Pip is resolved independently of Python, so a pip security release can refresh the tools snapshot without a CPython release. CPython's embedded `ensurepip` wheel remains the vendor-supplied wheel and is checked against the certificate-security floor rather than rewritten.

The base upgrades inherited Debian packages, requires the eMudhra fixed CA package, and checks that the affected root and cross-sign trust paths are absent. Bun, Node, uv and Electron use their corresponding patched releases. Zellij and Nushell resolve updated compatible Rust dependencies, and build checks inspect their actual compiled certificate-verifier/root-store versions. Guest activation supplies system trust defaults for Python/OpenSSL, Requests and uv, including SSH sessions. Explicit application trust overrides and old virtual environments still need their own review.

Existing writable tool overlays survive a rebuild. Review `c0 tools --detail` to inspect native changes; there is no need to discard the complete stage to pick up newly built default toolchains.

The `c0 tools` implementation in `bin/c0` defines snapshot identity, publication, restore, and collection behavior.

## Existing containers

`c0 start` resumes the same container. It recognizes both the prior writable host-bin/Git-config mounts and the current read-only host-bin/Git-config layout, while validating the checkout's other mount sources. It does not convert mounts, replace the filesystem, or change the tools selection of an existing container. Existing writable host mounts retain their original permissions; the read-only protections apply when creating a container with the current configuration.

`c0 stop` stops and removes the runtime container without deleting bind mounts or named volumes. The next `c0 start` creates a fresh runtime from the current built image and selected tools. `c0 restart` is exactly stop followed by start. A build leaves a running container alone until this cycle.

The writable container layer is disposable, as in the original design. Keep durable data in the declared host mounts and writable tools/launcher overlays; files stored elsewhere in the container are removed by stop.

Artifacts left by the removed lifecycle implementation are retained. Existing labeled overlay volumes can still be used by their original containers. Backup containers are excluded from primary discovery and do not block fresh creation. c0 does not restore, convert, rename, or delete those artifacts. Stop records the actual validated home-overlay volume name in per-instance checkout state under `.local/c0/` before removing the runtime. The next start reuses that same existing volume directly, including volumes left by earlier c0 implementations. This storage selection is independent of tools pins and survives builds and tools cleanup. Recorded volumes are required to exist; c0 does not silently create an empty replacement.

Builds use a private image tag and run an image check before publishing the normal runtime tag and tools selection. A missing Docker content/cache blob identified in a captured build or validation log triggers one uncached retry; ordinary package or network failures remain failures. Failed image validation retains the previously published image and checkout selection. Tools caches must contain their completeness marker and the exact resolved toolchain metadata. A tools path referenced by a running or stopped container is never overwritten. After removal, start can validate and promote a staged forced rebuild offline before creation. If a retained container still references that snapshot, start warns and retains the existing tools instead of overwriting shared data.

Terminal handling is portable: builds collect `xterm-256color` and the build caller's `TERM`. Interactive `c0 sh` and `c0 ssh` transfer the caller's definition using host `infocmp` and guest `tic` as UID 1000 into `~/.terminfo`; shell exec also forwards the caller's `TERM`. `c0 cp-term` remains available for an explicit system-wide copy.


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
| Restore boundary          | `c0 tools restore` discards configured tool uppers and resumes the same container; launcher state is retained                              |
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

Agents run as `dev` (`uid` 1000). The host operator can explicitly open a root shell with `c0 root`; this command is unavailable directly inside the guest. With network egress and bind mounts, they can:

- Read and write everything under `projects/`, assistant config dirs, `.config/`, `rules/`, and the guest `bin/` overlay
- Use mounted credentials (API tokens, `~/.gitconfig`, SSH keys in `auth/ssh/`)
- Use any key currently loaded in the host SSH agent
- Reach the public internet and `host.docker.internal`
- Run arbitrary code as `dev` inside the guest

c0dev intentionally shares selected host data with guest tools and applies a consistent cap/seccomp floor. Internal development servers published on the configured web port remain the developer’s responsibility. Host-side Git checks against an independent trusted source provide a tripwire for checkout modifications; the launcher overlay additionally keeps guest launcher edits separate from host files.

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
- If staged changes are wanted, run `c0 tools accept`; otherwise run `c0 tools restore`. Neither command replaces the guest filesystem. Restore refuses a pending selection change or a stage shared with another container.
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

`c0 tools accept` operates on the complete stage shown by `c0 tools --detail`; there are no hidden path exclusions. It pauses the runtime, snapshots each configured merged home overlay, copies the selected immutable snapshot to a new 64-hex path, replaces its overlaid paths with the merged snapshot, records the parent and stage digest, writes `.c0dev-complete` last, and updates the checkout pin. The running container keeps its mounted snapshot and stage, and the command warns about that fixed mount. Publication does not replace the guest or clear its files; the next stop/start selects the published snapshot.

`c0 tools restore` stops the container, clears only the configured tool uppers and their work directories, and starts the same container. It refuses before mutation if the checkout pin differs from the mounted snapshot or another container shares the stage. It retains launcher state and does not change the selected snapshot. Because the entire upper is the stage, direct writers that place logs, credentials, generated bytecode, or configuration beneath the overlay are included in either operation.

### Inspecting state

Current stage:

```bash
c0 tools
c0 tools --detail
```

Pinned `TOOLS_ID` values:

```bash
docker run --rm -v c0dev-tools-shared:/tools alpine ls -la /tools/pins
read -rp 'Folder ID from the list above: ' folder_id
docker run --rm -v c0dev-tools-shared:/tools alpine cat "/tools/pins/${folder_id}.pin"
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

The `tools` command behavior and state transitions are implemented in `bin/c0`.

## License

Licensed under the [MIT License](LICENSE). SPDX identifier: `MIT`. Third-party terms and unresolved licensing status are recorded in [THIRD-PARTY-NOTICES.txt](THIRD-PARTY-NOTICES.txt).
