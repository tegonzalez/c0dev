---
doc-graph: "When there is an intention to amend this document, first Adhere to [dc-doc-technical]; otherwise, do not modify."
---

# c0dev Tool Compatibility

## Purpose

Explain current default tools, native home-directory writes, immutable payloads, writable overlays, and host-persisted state. [Specification](spec.md) owns behavior; [tools contract](tool-store-contract.md) owns publication and restoration.

## Terminology

| Term            | Meaning                                                                        |
| --------------- | ------------------------------------------------------------------------------ |
| Default tool    | Tool supplied by the built runtime image or immutable tools payload.           |
| Native override | User-selected tool or writable path that differs from a built default.         |
| Tools stage     | Configured tool-home upper; distinct from launcher upper and direct host data. |

## General Contract

The current tools builder installs user tools as `dev` and packs `.cargo/bin`, `.rustup`, and complete `.local`. Runtime image content separately includes Bun and global assistant tools. Native writes beneath configured `.local` enter the tools upper. Declared host config/cache/XDG paths preserve ordinary state outside that stage.

The mounted manifest selects default Node/Python, package managers, uv/fnm, Semgrep, and mapped assistant commands through private cache shims. Stale generic launchers or fnm defaults in the persistent upper do not silently replace those defaults. Explicit interpreter paths, custom tools, and per-session version selection remain available. Other native `.local` commands continue through the merged upper/lower lookup; read-only lower content alone does not prove effective command identity.

## Environment

| Variable / surface | Current meaning                                                                    |
| ------------------ | ---------------------------------------------------------------------------------- |
| `TOOLS_PREFIX`     | Selected immutable payload at `/tools/current`.                                    |
| `XDG_CONFIG_HOME`  | Guest `.config`, backed by the declared host configuration directory.              |
| `XDG_CACHE_HOME`   | Guest `.cache`, backed by the declared host cache directory.                       |
| XDG data/state     | `.local-rw/share` and `.local-rw/state`, backed by host `.local`.                  |
| `CARGO_HOME`       | Guest `.cache/cargo`, backed by host cache.                                        |
| `RUSTUP_HOME`      | Selected `/tools/current/.rustup`; ordinary rustup updates disabled by activation. |
| `UV_CACHE_DIR`     | Guest `.cache/uv`, backed by host cache.                                           |
| Guest launchers    | `/home/dev/bin` uses its own upper over read-only host `/run/c0/host-bin`.         |

Host-backed XDG paths are data/state storage, not the default executable prefix. The current [activation](../bin/activate) and [runtime entrypoint](../docker/docker-entrypoint.sh) define exact emitted environment values.

## Current Tool Matrix

| Tool class              | Built location and acquisition                                                                              | Runtime state and update boundary                                                                                         |
| ----------------------- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Bun / bunx              | Resolved base/runtime image release                                                                         | Built defaults change through build; runtime files remain separate from tools-stage publication.                          |
| uv / uvx                | `.local/bin` and supporting resources; resolved uv installer                                                | Host uv cache; manifest-bound defaults; input verification remains separately required.                                   |
| Managed Python / pip    | `.local/share/uv/python` and selected launchers                                                             | Built Python 3.15 and resolved pip defaults; explicit project interpreters remain separate.                               |
| fnm / Node / npm / pnpm | `.local/share/fnm` and managed Node 22 tree                                                                 | fnm installs Node; its selected npm installs npm/pnpm in that prefix; per-session selections preserve custom aliases.     |
| Cursor / Droid / Devin  | User-tool resources acquired by current upstream installers                                                 | Config/cache and direct native writes may persist or stage; installer success is not full input proof.                    |
| Semgrep                 | uv-managed environment in `.local/share/uv/tools`                                                           | Built version and certificate-trust requirements; generated state may stage; no complete dependency hash lock is claimed. |
| Rustup / Cargo tools    | `.rustup` and `.cargo/bin`; current build uses Cargo for fd, ripgrep, ast-grep, zellij, Nu, and cargo-cache | Host registry cache; immutable default payload; compiled security-library checks remain part of the build.                |
| Bun assistant globals   | Runtime Dockerfile global installs                                                                          | Some selectors still float; tools acceptance does not rebuild runtime globals.                                            |
| Orca                    | Runtime image through `docker/install-orca.sh`                                                              | Guest service controlled by `c0 orca`; no marked-package publication route exists.                                        |
| System packages         | Base/runtime image and disposable guest layer                                                               | Explicit guest-root administration remains within runtime controls; durable defaults require build inputs.                |

The [tools Dockerfile](../docker/Dockerfile.tools) and [runtime Dockerfile](../docker/Dockerfile.runtime) support this current-source inventory. The [locked-acquisition design](design.md#locked-acquisition) governs the intended construction baseline and is not yet implemented. It retains every tool and native payload/state layout while replacing floating acquisition with verified exact inputs. The local release-discovery executable is not a supported dependency of that baseline. `c0 build`, Dockerfiles and acquisition scripts must consume the same [input signature file](../docker/signatures.json) before using newly fetched data. c0dev-owned content bindings use SHA-256; native package integrity retains SHA-512 only where that package solution uses it. Recorded input signatures and frozen selections do not establish that the current installer enforced them or that QA passed.

npm/npx execute package entrypoints through the selected Node interpreter. pnpm entrypoints may be JavaScript modules or native executables; activation reads the installed package’s `bin` metadata and invokes the appropriate form. Installation location alone does not establish another bundled Node runtime or publisher-bound acquisition verification.

## Display Semantics

Stage statuses describe filesystem relationships, not safety or canonical eligibility. New paths can be executables, dependencies, logs, credentials, or databases. Default display may summarize additions; detailed display supplies the full observable path set. Neither one inspects all file contents for secrets.

## Acceptance Consequences

Acceptance creates a complete immutable tools payload and derived runtime artifact. The existing guest continues using its mounted lower and stage until a later lifecycle replacement. Restoration clears configured tools upper/work and resumes the same guest, retaining launcher state and direct host data. Accepted archives bind captured content and metadata but do not establish source reproducibility, publisher-bound acquisition verification, or release-security clearance.

## Adding A Tool

A new default tool enters `docker/signatures.json`, the single construction-input authority, with its applicable subordinate native dependency lock and build identity. The signature file binds each such lock by SHA-256 before the trusted native manager consumes it. User-tool installers run unprivileged, with all consumed inputs subject to the [construction contract](spec.md#build) and [security requirements](spec.md#containment). Document native payload/support state, XDG behavior, direct writes, update behavior, and built/transitive dependency coverage. Verified package/archive contents inherit their enclosing trust; separately fetched inputs use the [family verification procedures](design.md#locked-acquisition). Deliberate runtime-native updates remain guest actions and cannot change the reviewed construction signature file. Native optional installation uses existing guest facilities; this branch provides no `c0 pkg` command or named-environment shell facade.
