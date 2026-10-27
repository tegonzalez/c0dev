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
| Workspace runtime    | Isolate containers by build and working folder while sharing build artifacts.               |
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
- Storage: Reads the selected tools lower and writes the workspace overlay-stage volume while entering the runtime mount namespace.
- Use: Mounts writable `.local` into `runtime`; the helper exits immediately after the mount succeeds.

#### `runtime`

- Type: Long-running development guest instance.
- Lifetime: Shared by repeated commands for one mode/build/working-folder tuple. Stop removes the workspace runtime and retains persistent mounts and volumes; restart runs stop followed by start.
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
- Use: Stores immutable build toolsets, accepted snapshots, and temporary extraction/publication paths. Docker artifact and container references protect live payloads.

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

| Term                      | Meaning                                                                                         |
| ------------------------- | ----------------------------------------------------------------------------------------------- |
| checkout / working folder | The real host path of this c0dev source tree; symlink spellings do not create another workspace |
| guest                     | A running c0dev container                                                                       |
| dev user                  | Default guest user, UID 1000; use `c0 sh`                                                       |
| recipe identity           | Path-independent hash of the Dockerfiles and stable copied build inputs                         |
| build identity            | Recipe identity plus the canonical resolved release manifest; shared within one `C0_MODE`       |
| `TOOLS_BUILD_ID`          | Content identity of the base/tools recipe and resolved toolchain manifest                       |
| `TOOLS_ID`                | Immutable tools payload identified by a published Docker image or an actual container mount     |
| tools volume              | Mode-scoped Docker volume containing immutable `/tools/opt/<TOOLS_ID>/` snapshots               |
| writable stage            | Workspace OverlayFS upper containing runtime writes beneath configured tool-home paths          |
| workspace                 | Mode plus real working folder; owns persistent host mappings and home-overlay storage           |
| instance                  | Mode/build/working-folder container identity, carried by Docker labels                          |

## Host requirements

**Status (fact):** Alpha — validated on the author's workstation only.

| Requirement | Version or note                                                      |
| ----------- | -------------------------------------------------------------------- |
| macOS       | Apple M-series, Tahoe v26.6.2                                        |
| OrbStack    | orbctl 2.2.3 (20963)                                                 |
| Terminal    | Ghostty v1.3.1                                                       |
| Xcode       | Required for `infocmp` during image build                            |
| Python      | 3.9+ at `/usr/bin/python3` for host helpers and credential transport |

## Image summary

| Property    | Value                                                 |
| ----------- | ----------------------------------------------------- |
| Base distro | Debian from the resolved `oven/bun` release           |
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

| Command                                          | Purpose                                                                                     |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------- |
| `c0 build [-f]`                                  | Build or reuse validated shared tools, base, and runtime artifacts; publish through Docker. |
| `c0 start [--least-privilege]`                   | Reuse the matching build/workspace container, or create it from the published shared image. |
| `c0 stop`                                        | Stop and remove this workspace's runtimes; retain bind mounts and named volumes.            |
| `c0 restart [--least-privilege]`                 | Run stop, then start with the supplied start arguments.                                     |
| `c0 sh` / `c0 root` / `c0 ssh [-Y] [command...]` | Attach as dev, root, or dev over SSH. `ssh --keygen` prepares SSH keys.                     |
| `c0 status` / `c0 logs [svc]`                    | Inspect this instance or view service logs.                                                 |
| `c0 tools [--detail\|accept\|restore]`           | Inspect, publish, or discard the writable tools stage; see the tools behavior below.        |
| `c0 orca [start\|stop\|status]`                  | Check or manage the guest Orca service.                                                     |
| `c0 seccomp-upgrade [--dry-run]`                 | Check for or apply a newer Moby seccomp profile.                                            |
| `c0 clean [-a]`                                  | Collect unused tools; refuse while any container references the store.                      |
| `c0 cp-term`                                     | Copy caller terminfo into the guest system terminfo store.                                  |
| `c0 help`                                        | Show command help.                                                                          |

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
c0 ssh                    # SSH as dev; client keys stay in host-only auth/ssh-client/
c0 ssh -Y                 # SSH with trusted X11 forwarding (host X server required)
c0 ssh --keygen           # Prepare separate host client and guest server/auth keys
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
- Guest server keys and public authorization live in gitignored `auth/ssh/`; management client keys and host `known_hosts` live in host-only `auth/ssh-client/`, which is never mounted in the guest. Key preparation occurs on normal setup or `c0 ssh --keygen`; it preserves the server key, retains legacy management keys in the private client archive, and preserves unrelated authorizations. Pubkey auth only.
- Connect: `c0 ssh` (same project-path behavior as `c0 sh`). Override: `C0DEV_SSH_PORT=2223 c0 start`.
- Trusted X11: start a host X server, ensure `DISPLAY` is set, then connect with `c0 ssh -Y`. The image includes `xauth`, and c0 enables `X11Forwarding` in its generated guest `sshd_config`.

### Per-session credential environment

Optional gitignored `auth/.env` supplies literal `NAME='value'`, `NAME="value"`, or `export NAME=...` assignments. Shell, guest-root, SSH, and service-launch sessions receive those values in the guest environment without putting values in transport arguments or changing host controls. Empty values, quoted punctuation, Unicode, and later duplicate assignments are preserved. Names starting `C0_SESSION_ENV` are reserved for the private handoff. Interactive input, exit statuses, project navigation, and trusted X11 remain available.

The management client directory is private to the host; existing guest configuration/data mounts and the optional guest SSH-agent relay remain separate. Key preparation updates files only when invoked, and does not restart or recreate a running guest. Existing client/server keys are retained or archived; private material must stay out of Git and logs.

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

| Host path       | Guest path                | Role                                                                                         |
| --------------- | ------------------------- | -------------------------------------------------------------------------------------------- |
| `.claude/`      | `/home/dev/.claude`       | Assistant state                                                                              |
| `.cache/`       | `/home/dev/.cache`        | Mutable tool caches (cargo registry, uv); `c0` never purges                                  |
| `.config/`      | `/home/dev/.config`       | Application config                                                                           |
| `.codex/`       | `/home/dev/.codex`        | Assistant state                                                                              |
| `.local/`       | `/home/dev/.local-rw`     | Host-visible XDG data and state                                                              |
| `rules/`        | `/home/dev/rules`         | Project rules                                                                                |
| `projects/`     | `/home/dev/projects`      | Sources and build outputs                                                                    |
| `bin/`          | `/run/c0/host-bin:ro`     | Host launcher/helper lower; writable guest view at `/home/dev/bin` uses OverlayFS            |
| `auth/ssh/`     | `/home/dev/.ssh`          | Guest server/auth and durable SSH state; host management client keys stay outside this mount |
| `.claude.json`  | `/home/dev/.claude.json`  | Assistant credentials file                                                                   |
| `~/.gitconfig`  | `/home/dev/.gitconfig:ro` | Host Git identity and settings; guest cannot change the host file                            |
| `tools-shared`  | `/tools/current:ro`       | Shared immutable payload selected from Docker artifact metadata                              |
| `home-overlays` | `/run/c0/overlay-state`   | Workspace writable tool stage, launcher upper, and OverlayFS work data                       |

The guest `/home/dev/bin` overlays the read-only host `bin/` lower. Guest edits persist in a separate launcher upper across restarts and do not change host scripts. The launcher upper is excluded from `c0 tools accept` and `c0 tools restore`; host updates remain visible for paths the guest has not overridden.

Canonical executables and resources come from the selected read-only tools snapshot. Native writes beneath an overlaid tool-home path enter the workspace writable stage. XDG data/state is redirected to the host `.local/`; direct writers that ignore XDG remain part of the stage and are therefore included by `c0 tools accept` or removed by `c0 tools restore`.

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

1. Validates the declared host mount paths.
1. Resolves current stable releases from official upstream metadata, keeping Node on 22 and Python on 3.15, and produces a canonical release manifest.
1. Derives path-independent recipe, build, and tools identities. Working-folder paths do not enter shared artifact identities.
1. Builds or reuses the mode/build base image and mode-scoped tools payload. Tools extraction writes a completeness marker only after the payload is complete.
1. Prepares the portable `xterm-256color` image definition. Caller terminal definitions are synchronized when attaching.
1. Builds or reuses the mode/build runtime image. New images pass a networkless UID-1000 launch check before publication.
1. Publishes the completed runtime image under its shared build tag and recipe alias. Docker image labels identify its build, mode, recipe, tools payload, and base image.

Every `c0 build` resolves the latest stable Bun, uv, fnm, Node 22 patch, Python 3.15 patch, pip, and Semgrep. npm and pnpm select the newest stable versions compatible with the selected Node 22 release. Prereleases, releases below the security floors, malformed metadata, and upstream lookup failures stop the build; failed builds leave the previously published shared runtime image intact.

The canonical manifest and Dockerfile recipe determine shared artifact identities. A new resolved release changes the build and tools identities even when the Dockerfiles are unchanged. Identical mode/recipe/release inputs in different working folders reuse the same completed tools, base, and runtime artifacts. Containers add the working-folder identity. A running container keeps its fixed image and tools mount until stopped; the next start uses the current published shared image. The exact versions are passed to both image builds and verified during installation; the manifest is retained in `/tools/current/.c0dev-toolchain.json` and `/tools/current/.local/share/c0/toolchain.json` for inspection.

`c0 build -f` bypasses completed-artifact reuse, pulls the selected base, and bypasses Docker layer caching. Image builds that are needed use `--pull`. This release resolver is not a CVE scanner: same-version distro package changes, independently vendored application runtimes, Rust transitive changes, and existing project environments still need their own security review or a forced rebuild.

Normal `c0 sh` and `c0 ssh` select the mounted snapshot's Node/Python, package-manager and uv defaults, even when a persistent home overlay contains older generic launchers or fnm defaults. Selection uses private cache shims without deleting staged files or rewriting custom fnm aliases. Node/Python versions remain available for explicit per-session selection. Login, status, start, and SSH do not resolve toolchain releases or install tools; `c0 build` resolves toolchain releases.

Debian's `/usr/bin/python3` remains available for system-package shebangs and dependencies; replacing or removing it would break those consumers. Existing project virtual environments keep their own interpreter and packages. Pip is resolved independently of Python, so a pip security release can refresh the tools snapshot without a CPython release. CPython's embedded `ensurepip` wheel remains the vendor-supplied wheel and is checked against the certificate-security floor rather than rewritten.

The base upgrades inherited Debian packages, requires the eMudhra fixed CA package, and checks that the affected root and cross-sign trust paths are absent. Bun, Node, uv and Electron use their corresponding patched releases; the reviewed Orca package is 1.4.239 with Electron 43.8.1. Zellij and Nushell resolve updated compatible Rust dependencies, and build checks inspect their actual compiled certificate-verifier/root-store versions. Guest activation supplies system trust defaults for Python/OpenSSL, Requests and uv, including SSH sessions. Explicit application trust overrides and old virtual environments still need their own review.

Existing writable tool overlays survive a rebuild. Review `c0 tools --detail` to inspect native changes; there is no need to discard the complete stage to pick up newly built default toolchains.

The `c0 tools` implementation in `bin/c0` defines snapshot identity, publication, restore, and collection behavior.

## Sharing and lifecycle

| Resource                  | Sharing scope                                                                            |
| ------------------------- | ---------------------------------------------------------------------------------------- |
| TOOLS, BASE, IMAGE        | `C0_MODE` plus build identity; reused across working folders                             |
| CONTAINER                 | Mode/build identity plus real working folder; reused by repeated commands for that tuple |
| Persistent workspace data | Mode plus real working folder; retained across runtime removal                           |

c0 derives selection from Docker images, tags, labels, containers, mounts, and named volumes. It creates no persistent c0 selector files, checkout pins, saved volume references, or replacement selector objects. Temporary build contexts and embedded immutable release manifests are build inputs and artifact contents.

`c0 start` reuses the matching build/workspace container, or creates one from the completed shared image. Existing supported writable-bin/Git-config and read-only launcher/Git-config layouts remain operable without conversion. Read-only host protections apply to newly created containers. Different builds cannot concurrently mount the same workspace's writable home overlays; stop the workspace before starting its replacement build.

`c0 stop` validates ownership, stops and removes this workspace's runtimes, and retains host binds and named volumes. `c0 restart` is exactly stop followed by start. To apply a newly built artifact to a running workspace:

```bash
c0 build
c0 stop
c0 start
```

The writable container layer is disposable. Keep durable files in declared host mounts or writable tools/launcher overlays; files elsewhere in the container are removed by stop.

Home-overlay storage is discovered from Docker. Existing canonical workspace storage and unambiguous labeled legacy volume lineage are reused directly. Ambiguous or conflicting Docker storage is left untouched for review. Retained backup containers are excluded from runtime selection. There is no data conversion, root-filesystem capture, or upgrade path.

Completed artifacts are validated before reuse or publication. Missing Docker content identified in captured diagnostics can trigger one uncached retry; package or network failures remain failures. Referenced tools payloads are never overwritten. A forced tools rebuild can remain staged while a retained container still references the existing payload; start reports that condition rather than changing shared data.

Terminal handling is portable: the image contains `xterm-256color`, and interactive `c0 sh` and `c0 ssh` transfer the caller's definition using host `infocmp` and guest `tic` as UID 1000 into `~/.terminfo`. Shell exec forwards the caller's `TERM`. `c0 cp-term` remains available for an explicit system-wide copy.


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

Runtime containers are **not Docker privileged** in either policy. `C0_SECURITY` accepts `guest-admin` (the default) or `least-privilege`; both use the Moby default seccomp profile and `no-new-privileges:true`. The `guest-admin` overlay (`docker-compose.security-guest-admin.yaml`) drops all capabilities, then restores `DAC_OVERRIDE`, `CHOWN`, and `FOWNER` for guest administration. The `least-privilege` overlay (`docker-compose.security-least-privilege.yaml`) drops all capabilities and restores none. Select it with `C0_SECURITY=least-privilege` or `c0 start --least-privilege`.

| Control              | Setting                                                                                           |
| -------------------- | ------------------------------------------------------------------------------------------------- |
| Privileged           | `false`                                                                                           |
| Capabilities         | `cap_drop: ALL`, then add `DAC_OVERRIDE`, `CHOWN`, `FOWNER`                                       |
| Privilege escalation | `no-new-privileges:true`                                                                          |
| Syscalls             | Moby default seccomp profile (vendored under `docker/seccomp/`, checksum-verified at start/build) |

`DAC_OVERRIDE`, `CHOWN`, and `FOWNER` support `c0 root` and package installs inside the guest without running `sshd` setuid or granting broad Linux capabilities. They are **guest-admin helpers**, not host-root equivalents. The UID 1000 `c0 sh` process does not receive them as effective capabilities; it runs under the same seccomp and no-new-privileges policy.

`sshd` listens on guest port `2222` and runs as the `dev` user (no setuid). The host publishes **`127.0.0.1:<port>` only**.

Native upgrades run inside the existing restricted runtime and can write only its OverlayFS upper, not the shared tools volume. `c0 tools accept` pauses the runtime for a consistent snapshot, uses the existing networkless namespace helper to read the merged view, and invokes a separate networkless publisher. The publisher creates a new immutable tools payload and publishes its derived shared runtime image; it never modifies a mounted payload in place.

### Hardening in place

| Control                   | Mechanism                                                                                                                                 |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Immutable accepted tools  | Runtime mounts only `/tools/opt/<TOOLS_ID>` at `/tools/current:ro`; other shared snapshots are not visible                                |
| Explicit publication      | Runtime writes remain in its upper until the host operator runs `c0 tools accept`; runtime processes never receive volume-write authority |
| Restore boundary          | `c0 tools restore` discards configured tool uppers and resumes the same container; launcher state is retained                             |
| Loopback SSH              | Pubkey-only inbound login; guest auth in `auth/ssh/`, host client/trust in unmounted `auth/ssh-client/`                                   |
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
- Keep secrets in gitignored paths; never commit `auth/`, including host client archives, or assistant token files.
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
- Docker labels identify the mode, build, recipe, workspace, instance, and tools payload; `c0 status` reports discovered containers.

## Tools publication and garbage collection

Build-produced and accepted tools payloads are immutable. Docker images and running or stopped containers identify their referenced payloads. Garbage collection protects those references and conservatively retains accepted snapshots and unknown legacy data.

### Stage acceptance and restore

`c0 tools accept` publishes the complete stage reported by `c0 tools --detail` as a new immutable tools payload and an ordinary shared runtime artifact. Its Docker labels publish the derived build and tools identity. The running container keeps its mounted tools and writable stage until stop/start; acceptance does not replace its filesystem or clear its files. Launcher state is excluded from tools acceptance and restore.

`c0 tools restore` stops the container, clears only the configured tool uppers and work directories, and starts that same container. It refuses before mutation when the Docker-published tools differ from the mounted snapshot or another container shares the stage. It retains launcher state. Direct writers that put logs, credentials, bytecode, or configuration beneath a configured tools overlay are part of its stage.

### Inspection and cleanup

Inspect the current writable stage with `c0 tools` or `c0 tools --detail`. `c0 status` reads Docker-owned workspace/container information without consulting a saved selector.

`c0 clean` refuses while containers reference the store and otherwise collects unused, verifiably rebuildable cache payloads. `c0 clean -a` also refuses published-image references and unknown retained data before removing an unused tools volume. Neither command removes guest containers, host caches, projects, or persistent home-overlay volumes.

### Safety guarantees

- Runtime guests receive read-only tools-volume mounts.
- Published images and container references protect their tools payloads.
- Complete referenced snapshots are not replaced in place.
- Acceptance and restore require an explicit host command.
- Failed builds do not trigger garbage collection or replace the published runtime image.
- Completeness markers and release manifests validate immutable artifact contents; they are not runtime-selection registries.

The tools commands are implemented in `bin/c0`.

## License

Licensed under the [MIT License](LICENSE). SPDX identifier: `MIT`. Third-party terms and unresolved licensing status are recorded in [THIRD-PARTY-NOTICES.txt](THIRD-PARTY-NOTICES.txt).
