---
doc-graph: "When there is an intention to amend this document, first Adhere to [dc-doc-spec]; otherwise, do not modify."
---

# c0dev Specification

## Purpose

Define the public commands, observable execution modes, state boundaries, and tool-stage lifecycle implemented by c0dev.

## Terminology

| Term              | Meaning                                                                                                  |
| ----------------- | -------------------------------------------------------------------------------------------------------- |
| Runtime guest     | Long-running non-privileged c0dev service container                                                      |
| Runtime root lane | UID-0 process entered through `c0 root` inside the runtime guest                                         |
| Build toolset     | Complete immutable `/tools/opt/<TOOLS_BUILD_ID>` produced by `c0 build`                                  |
| Selected snapshot | Complete immutable `/tools/opt/<TOOLS_ID>` selected by this checkout's pin                               |
| Writable stage    | Complete per-instance OverlayFS upper containing runtime writes beneath configured tool-home paths       |
| Accepted snapshot | New selected snapshot formed from the previous selected snapshot plus the complete merged writable stage |

## Model

`c0 build` is the only build command. It installs non-apt tools as `dev`, packs `.cargo/bin`, `.rustup`, and the complete builder-created `.local`, and publishes the result beneath its build hash.

The runtime mounts only its selected snapshot at `/tools/current:ro`. An OverlayFS mount exposes the selected `.local` as lower and a persistent per-instance Docker volume as upper. Native updaters therefore work at `~/.local` without receiving tools-volume write access.

`c0 tools` is stage management, not installation or build orchestration. The whole upper is one stage; c0 does not infer which paths are executable payload, auth, logs, cache, configuration, or generated state.

## Public Surface

| ID        | Shape                                       | Observable behavior                                                                                  |
| --------- | ------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `C0-PS1`  | `c0 build [-f]`                             | Builds tools and runtime image; `-f` disables build cache and forces tool extraction                 |
| `C0-PS2`  | `c0 tools`                                  | Summarizes the complete writable stage and lists modified, deleted, and opaque paths                 |
| `C0-PS3`  | `c0 tools --detail`                         | Lists every observable staged path using `A`, `M`, `D`, or `O` status                                |
| `C0-PS4`  | `c0 tools accept`                           | Publishes the complete merged stage as a new selected immutable snapshot and recreates the runtime   |
| `C0-PS5`  | `c0 tools restore`                          | Discards the complete upper, retains the selected snapshot, and recreates the runtime                |
| `C0-PS6`  | `c0 start\|stop\|restart\|status`           | Controls or inspects the realpath-keyed runtime instance                                             |
| `C0-PS7`  | `c0 sh`, `c0 ssh`, `c0 root`                | Enters the running guest only after quiet overlay validation                                         |
| `C0-PS8`  | `/tools/current:ro`                         | Selected-volume subpath visible to runtime; other shared snapshots are not mounted                   |
| `C0-PS9`  | `/run/c0/overlay-state`                     | Per-instance persistent writable upper/work volume                                                   |
| `C0-PS10` | Host state paths                            | Direct host `.config`, `.cache`, `.local`, and projects; `.local` appears at `.local-rw` for XDG use |

## Invariants

- The runtime guest is not privileged and has no Docker, mount, or publication authority.
- The selected snapshot is mounted read-only, including for `c0 root`.
- Runtime tool writes enter the stage and never change a complete snapshot.
- `c0 tools accept` and `restore` require an explicit host command and operate on the entire stage.
- Acceptance creates a new 64-hex snapshot, records parent and stage digest, and writes `.c0dev-complete` last.
- The checkout pin changes only after the accepted snapshot is complete.
- A failed acceptance does not clear the upper or replace the selected snapshot.
- Accept and restore recreate the runtime because an OverlayFS lower cannot be replaced safely in place.
- Normal `c0 sh` and `c0 ssh` activation emits no overlay diagnostics.

## Contracts

The exact snapshot, pin, stage, acceptance, restoration, and failure rules are owned by the [Tool-store contract](tool-store-contract.md). Process privileges and residual exposure are owned by the [Security model](security-model.md). Per-tool native path behavior is described by [Tool compatibility](tool-compatibility.md).

## Semantics

### Build

`c0 build` produces `TOOLS_BUILD_ID` from `Dockerfile.base` and `Dockerfile.tools`. It builds the tools stage as `dev`, extracts through `/tools/tmp/<id>.partial`, and writes the completeness marker last. A successful build pins that build toolset for the checkout.

### Display

`c0 tools` requires a running, valid overlay. Default output reports counts for added, modified, deleted, and opaque paths; added paths are collapsed to one line while non-additive changes are shown. `--detail` expands all paths. Clean output is exactly a clean stage claim, not a tools-volume build claim.

### Accept

Acceptance pauses the runtime, snapshots each configured merged overlay through a short-lived networkless namespace helper, and resumes the runtime before publication. A separate networkless publisher copies the selected snapshot, replaces each configured overlaid path with its merged archive, records `.c0dev-accepted-from` and `.c0dev-stage-sha256`, writes `.c0dev-complete` last, and moves the candidate to `/tools/opt/<accepted-id>`.

After publication, c0 pins the accepted ID, captures the current ports and security mode, removes the runtime, clears upper/work state, and recreates the runtime with only `opt/<accepted-id>` mounted at `/tools/current:ro`.

### Restore

Restore retains the selected pin, removes the runtime, clears the complete upper/work volume, and recreates the runtime against the same selected snapshot. The discarded upper is not recoverable through c0.

### Runtime Root Administration

`c0 root` starts UID 0 inside the existing runtime under the same seccomp profile and documented capability set. `apt` changes the container writable layer, never the selected tools snapshot, and is not guaranteed across destructive recreation.

## Validation

- `c0 tools` and `--detail` must be read-only and must agree on stage counts.
- Runtime inspection must show `/tools/current` read-only and no mount of `/tools/opt` or store metadata.
- Accept must leave the parent complete, write the new completeness marker last, and update the pin afterward.
- Restore must retain the selected ID and remove every observable upper entry.
- Interrupted snapshot capture must resume the runtime and remove host temporary archives.
- `c0 sh` and `c0 ssh` must enter quietly after successful overlay validation.

## Diagnostics

`c0 status` reports the selected ID, selected read-only subpath, overlay health, instance state, ports, security mode, host mappings, and pins. `c0 tools` owns user-facing stage disposition. Overlay mount failures remain startup and status errors rather than shell-activation traces.

## Boundaries

- Whole-stage acceptance may include direct non-XDG logs, credentials, bytecode, databases, or configuration.
- c0 does not update code already executing inside a process.
- The macOS bind filesystem currently cannot serve as a writable OverlayFS upper; the upper/work layer remains a per-instance Docker volume.
- `c0 tools` does not invoke installers, resolve versions, or rebuild images.
- Docker-operator and macOS-account compromise are outside the guest boundary.
