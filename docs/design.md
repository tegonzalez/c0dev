---
doc-graph: "When there is an intention to amend this document, first Adhere to [dc-doc-design]; otherwise, do not modify."
---

# c0dev Design

## Purpose

Define how c0dev combines an immutable selected tool snapshot with a persistent writable runtime stage while preserving a constrained long-running guest and a low-cognitive-load host interface.

## Orientation

This document is for maintainers changing `bin/c0`, Compose mounts, overlay helpers, snapshot publication, or lifecycle behavior.

## Terminology

The [Specification](spec.md) defines runtime guest, selected snapshot, writable stage, and accepted snapshot. This design uses those terms without redefining them.

## Design Goals

- Keep `c0 build` as the only construction command.
- Make the complete writable upper visible through one stage interface.
- Keep runtime tools-volume access selected and read-only.
- Require explicit host authority for acceptance or restoration.

## Module Inventory

| Component            | Source                                         | Responsibility                                                                  |
| -------------------- | -------------------------------------------    | ------------------------------------------------------------------------------- |
| Host router          | `bin/c0`                                       | Instance selection, lifecycle, snapshots, publication, pins, and diagnostics    |
| Build definition     | `docker/Dockerfile.base`, `.tools`, `.runtime` | OS image and build-produced default tools                                       |
| Runtime guest        | Compose service `c0dev`                        | Development processes under runtime seccomp/capability policy                   |
| Overlay policy       | `docker/home-overlays.conf`                    | Maps guest-home-relative paths to selected-snapshot-relative lowers             |
| Overlay checker      | `docker/c0-overlay-check`                      | Validates mounts and emits stage porcelain                                      |
| Overlay helper       | Host-launched Alpine plus `nsenter`            | Mounts OverlayFS inside the runtime mount namespace                             |
| Snapshot helper      | Same bounded helper class                      | Reads merged paths while runtime is paused                                      |
| Publisher            | Fixed inline host-controlled script            | Creates a complete accepted snapshot and updates checkout selection             |
| Shared tools volume  | `${SHARED_TOOLS_VOLUME}`                       | Immutable build/accepted snapshots, temporary publication paths, and pins       |
| Overlay-state volume | `${C0_INSTANCE_ID}-home-overlays`              | Persistent per-instance upper and work directories                              |

## Architecture

### Build Path

`c0 build [-f]` is the only construction path. `dockerfile-concat` creates build inputs from base plus tools/runtime fragments. The tools builder installs non-apt tools after `USER dev`. The host extracts `.cargo/bin`, `.rustup`, and the complete `.local` tree through `/tools/tmp/<TOOLS_BUILD_ID>.partial`, writes `.c0dev-complete` last, and pins the complete build ID after overall build success.

`-f` changes Docker cache and extraction disposition only. It does not change the `c0 tools` interface.

### Runtime Mount Path

Compose mounts only the selected volume subpath `opt/${TOOLS_ID}` at `/tools/current:ro`. This is narrower than mounting the complete shared volume and prevents a runtime from browsing other accepted snapshots or metadata.

At start or restart, the host validates the overlay policy and launches a short-lived networkless helper. The helper joins the runtime mount namespace and mounts:

- lower: `/tools/current/<tools-relative-path>`
- upper: `/run/c0/overlay-state/upper/<overlay-name>`
- work: `/run/c0/overlay-state/work/<TOOLS_ID>/<overlay-name>`
- target: `/home/dev/<guest-relative-path>`

The helper exits after verification. Runtime PID 1 waits for every configured target to become OverlayFS before starting sshd and reporting readiness.

### Stage Inspection

The checker reads upper entries directly and emits a porcelain status:

- `A`: no corresponding lower entry
- `M`: non-directory upper entry shadows a lower path
- `D`: whiteout hides a lower path
- `O`: opaque upper directory hides lower directory content

`c0 tools` summarizes counts and expands non-additive changes. `c0 tools --detail` prints every emitted path. Normal shell activation does not run the checker; start, guest-entry guards, status, and tools commands own validation.

### Acceptance

Acceptance uses the runtime upper as the writable stage; it does not run installers or rebuild Dockerfiles.

1. Validate that the runtime and overlays are ready and that the stage is non-empty.
1. Pause the runtime to prevent a changing merged view.
1. For each policy row, launch a networkless namespace helper and stream a tar archive of the merged guest path to a mode-0700 host temporary directory.
1. Reject archive members outside the configured guest-relative root.
1. Resume the runtime before publication.
1. Hash the ordered archive digests and derive a new ID from the selected parent plus stage digest.
1. Launch the networkless publisher with snapshots RO and the shared tools volume RW.
1. Copy the selected parent into a temporary candidate and replace configured paths from the archives.
1. Record parent and stage digest, normalize ownership, and write completeness last.
1. Move the candidate to its immutable ID and update the checkout pin.
1. Preserve ports and security mode, remove the runtime, clear upper/work, and recreate against the accepted ID.

The publisher does not modify the selected parent. A complete identical target is reused; an incomplete existing target blocks publication.

### Restoration

Restore is intentionally smaller: retain the selected pin, preserve ports and security mode, remove the runtime, clear the complete upper/work volume, and recreate against the same selected ID. No build or volume publication occurs.

### Selection

The per-checkout pin is both selection and GC protection. Command startup resolves a valid complete pinned ID and otherwise falls back to `TOOLS_BUILD_ID`. Compose receives the resolved `TOOLS_ID`; the container label records it for active-use protection.

Accepted snapshots are complete copies, so their parent need not remain mounted or GC-protected after acceptance. `.c0dev-accepted-from` retains provenance for inspection.

## Design Decisions

| ID        | Decision                                                                 | Rationale                                                                                   |
| --------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------- |
| `C0-D001` | `c0 tools` manages stage state and never builds                          | Keeps one build command and a simple clean/staged user model                                |
| `C0-D002` | The complete upper is the stage                                          | Generic path inference cannot distinguish arbitrary tool payload from native support state  |
| `C0-D003` | Accept creates a new immutable snapshot                                  | Runtime never needs tools-volume RW and complete parents are never mutated in place         |
| `C0-D004` | Accept and restore recreate the runtime                                  | Generic live replacement of an active OverlayFS lower is not reliable                       |
| `C0-D005` | Runtime mounts only its selected tools subpath                           | Whole shared-volume RO access would expose other checkout snapshots                         |
| `C0-D006` | Upper/work remain in a Linux Docker volume                               | OrbStack host bind mounts can mount as an OverlayFS upper but merged writes fail read-only  |
| `C0-D007` | XDG data/state uses host `.local-rw`                                     | Keeps common mutable state host-visible while preserving native merged `~/.local`           |
| `C0-D008` | Successful shell activation is silent                                    | Stage state is actionable only through status/tools commands, not every interactive attach  |

## Rejected Alternatives

- Copying built `.local` into a writable host directory: destroys the selected read-only execution baseline.
- Manual per-tool writable-path policy: cannot remain correct for arbitrary future native installers.
- Treating every upper override as an integrity failure: writable copy-up is the feature being provided.
- Making `c0 tools` another build/update coordinator: duplicates `c0 build` and increases cognitive load.
- Live lower remount after acceptance: unsafe for arbitrary open files, working directories, and OverlayFS upper reuse.
- Host-backed upper/work on current OrbStack/macOS binds: isolated validation produced `Read-only file system` on merged writes.

## Component Responsibilities

The host router sequences every Docker-authority operation. Guest helpers validate or inspect only their mounted/runtime namespace. The runtime owns user execution and stage writes but never selection or publication. The publisher owns completeness and immutable placement but never runtime mounts.

## API Shape

The public stage API is exactly `c0 tools`, `c0 tools --detail`, `c0 tools accept`, and `c0 tools restore`. Internal porcelain is tab-separated status plus path and is not a public stability promise beyond those commands.

## Workflow And Data Flow

Runtime writes flow to the upper. Display reads upper versus selected lower. Acceptance reads the merged view, creates a new complete snapshot, updates the pin, clears upper/work, and recreates runtime. Restoration skips snapshot creation and publication.

## Policy And Authority Boundaries

The [Specification](spec.md) owns commands and observable behavior. The [Tool-store contract](tool-store-contract.md) owns snapshot and stage transitions. The [Security model](security-model.md) owns capability and threat interpretation. This document owns implementation mechanisms and rationale.

## Upstreamable Surface

Overlay policy parsing, porcelain status, immutable snapshot layout, and selected-subpath Compose mounts are general mechanisms. OrbStack relay paths and macOS bind limitations are platform-specific integration.

## Private Implementation Surface

Temporary archive names, inline publisher shell, helper image choice, colorized messages, and internal function names may change while preserving the specification and contract.

## Constraints References

Changes must preserve [Constraints](constraints.md), especially read-only selected snapshots, no guest publication authority, no in-place complete-snapshot mutation, complete stage visibility, and checkout-visible `bin/` writes.

## Preservation Requirements

- Preserve unrelated host state and untracked workspace files.
- Preserve the selected parent until acceptance completes.
- Preserve runtime ports and security mode across accept and restore recreation.
- Preserve stage data on every failure before successful publication and pin update.

## Failure Modes

Snapshot capture always attempts to resume a paused runtime. Temporary archives are removed after success, failure, or interrupt. Publication failure leaves the stage intact. The pin changes only after completeness. Stage clearing occurs only after publication. If recreation fails, the immutable selected snapshot and persistent stage volume remain available to host diagnostics.

## Acceptance Criteria

- Runtime Compose configuration mounts only `opt/${TOOLS_ID}` at `/tools/current:ro`.
- `c0 tools` is read-only and does not invoke Docker build or package installation.
- Isolated publisher and clearing fixtures pass without altering non-target snapshots.
- Snapshot capture while paused observes the merged namespace-mounted overlay.
- Shell and SSH attachment emit no overlay summary on success.
- README, specification, contract, security reference, and command help describe the same command surface.
