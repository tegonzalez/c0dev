---
doc-graph: "When there is an intention to amend this document, first Adhere to [dc-doc-technical]; otherwise, do not modify."
---

# c0dev Security Model

## Purpose

Define the trust boundaries, capabilities, storage authority, and residual risks of runtime tool staging and host-authorized acceptance.

## Threat Model

| Boundary     | Scope                                                                                                                       |
| ------------ | --------------------------------------------------------------------------------------------------------------------------- |
| In scope     | Compromised runtime process, fetched updater code, accidental snapshot corruption, privilege expansion, cross-snapshot read |
| Out of scope | Operator controlling Docker or macOS, compromised OrbStack VM/kernel, trusted build-input compromise                        |
| Assumption   | One human owns the checkout; Docker and OrbStack are trusted infrastructure                                                 |

The objective is to keep runtime and updater authority from becoming Docker or tools-volume publication authority. c0dev is not a multi-tenant sandbox and does not protect mounted user data from code intentionally run in the guest.

## Process Variants

| Kind              | Lifetime   | UID      | Capabilities                                                                                         | Seccomp/NNP          | Network      | Writable authority                              |
| ----------------  | ---------- | -------- | ---------------------------------------------------------------------------------------------------- | -------------------- | ------------ | ----------------------------------------------- |
| Build             | Ephemeral  | root/dev | Docker build profile; non-apt tool installers run after `USER dev`                                   | Build profile        | Fetch        | Image layers and unpublished extraction path    |
| Runtime           | Long-lived | 1000     | Effective/permitted zero; bounded runtime admin set                                                  | Project seccomp; NNP | Guest egress | Runtime layer, host RW mounts, overlay stage    |
| Runtime root lane | Exec only  | 0        | `CHOWN`, `DAC_OVERRIDE`, `FOWNER`; no `SYS_ADMIN`, Docker socket, or publication authority           | Same as runtime      | Guest egress | Runtime layer, host RW mounts, overlay stage    |
| Overlay helper    | Ephemeral  | 0        | `SYS_ADMIN`, `SYS_PTRACE`, `SYS_CHROOT`, DAC read/write, ownership caps; unconfined seccomp; NNP     | Unconfined; NNP      | None         | Runtime mount namespace and overlay upper/work  |
| Snapshot helper   | Ephemeral  | 0        | Mount-namespace entry and read capabilities; unconfined seccomp; NNP                                 | Unconfined; NNP      | None         | Host-owned temporary archive stream             |
| Publisher         | Ephemeral  | 0        | `CHOWN`, `DAC_OVERRIDE`, `DAC_READ_SEARCH`, `FOWNER`; no `SYS_ADMIN`; read-only root filesystem; NNP | Default helper       | None         | Tools `opt`, `tmp`, and checkout pin metadata   |

The helper capability increase exists only in host-launched one-shot containers. PID 1 and user processes in the runtime never receive those capabilities. A rogue runtime must first cross a kernel or Docker boundary; it cannot obtain helper authority by compromising runtime PID 1 alone.

## Storage Boundaries

| Surface                        | Runtime access                            | Helper/publisher access                                      | Purpose                                                            |
| ------------------------------ | --------------                            | ---------------------------                                  | ------------------------------------------------------------------ |
| Selected `/tools/opt/<id>`     | `/tools/current:ro` only                  | Snapshot helper reads; publisher copies                      | Prevent runtime mutation and cross-snapshot browsing               |
| Other tools snapshots/metadata | Absent                                    | Host volume helpers only                                     | Prevent one runtime from reading accepted state from another       |
| Overlay upper/work volume      | RW through merged home and internal mount | Overlay/snapshot helper                                      | Persist runtime writes without weakening selected snapshot         |
| Host config/cache/XDG state    | Declared RW                               | Absent from publisher except when also written under overlay | Preserve ordinary user state directly on host                      |
| Docker socket                  | Absent                                    | Host c0 invokes Docker                                       | Prevent guest-to-daemon privilege expansion                        |
| SSH agent                      | Runtime relay when enabled                | Absent from helpers/publisher                                | Keep publication processes credentialless                          |

## Acceptance Boundary

Runtime updaters execute with the runtime's network and data authority. They can corrupt the stage, consume resources, and write any host surface already exposed to the guest. They cannot mark their output accepted or write the tools volume.

`c0 tools accept` is the operator authorization event. The runtime is paused while the namespace helper reads the merged overlay, then resumed before the publisher runs. The publisher receives the captured archives read-only and the tools volume read-write, has no network, and executes fixed host-controlled code. Completeness is written last and the pin changes afterward.

Acceptance approves the whole stage, not a tool-specific subset. Consequently, direct writers may place credentials, logs, databases, bytecode, or configuration into an accepted snapshot. The runtime mounts only its selected subpath to prevent cross-checkout browsing, but the Docker operator can inspect every volume and remains out of scope.

## Restore Boundary

`c0 tools restore` is an explicit destructive host operation. It removes the runtime before clearing upper/work state, retains the selected immutable snapshot, and recreates the runtime. It never modifies the selected snapshot or direct host paths outside the overlay volume.

## Residual Risks

| Risk                          | Exposure                                                                        | Control                                                                   |
| ----------------------------- | ------------------------------------------------------------------------------  | ------------------------------------------------------------------------  |
| Linux kernel or Docker escape | Helpers and runtimes share the OrbStack VM kernel                               | Short lifetimes, no helper network, NNP, narrow mounts, updated platform  |
| Whole-stage secret acceptance | Native non-XDG state may enter the accepted snapshot                            | Full `--detail` display, explicit accept, selected-subpath runtime mount  |
| Writable guest host mounts    | Agent can alter projects, configuration, credentials, and host helper scripts   | Deliberate single-user scope; minimize mounts and credentials             |
| Publisher snapshot integrity  | Runtime controls staged content and filenames                                   | Paused capture, path validation, fixed extraction root, completeness-last |
| Runtime apt drift             | Ad hoc libraries can diverge from the built ABI                                 | Treat as ephemeral; rebuild image for persistence                         |
| Accepted binary provenance    | Accepted snapshot records parent and archive digest, not source reproducibility | Build toolsets remain separate; accept is explicit operator authority     |

## Operational Verification

```bash
c0 status
c0 tools
c0 tools --detail
c0 ssh 'grep -E "^(Cap(Inh|Prm|Eff|Bnd|Amb)|NoNewPrivs|Seccomp):" /proc/1/status'
c0 ssh 'findmnt -T /tools/current -n -o TARGET,FSTYPE,OPTIONS'
```

Expected runtime evidence is a read-only `/tools/current`, no `/tools/opt` or tools metadata mount, zero effective/permitted capabilities for PID 1, NNP enabled, seccomp filtering enabled, and no Docker socket or mount capability.

## Failure Response

- Writable selected mount: stop the guest and reject startup.
- Snapshot failure: resume runtime and retain stage and selection.
- Publisher failure: retain prior selection and complete stage.
- Incomplete selected ID: warn and fall back to the complete build toolset.
- Uncertain pin or active-use protection: collect nothing.
