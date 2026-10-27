---
doc-graph: "When there is an intention to amend this document, first Adhere to [dc-doc-contract]; otherwise, do not modify."
---

# c0dev Tool-Store Contract

| Metadata      | Value                         |
| ------------- | -------------------------     |
| Contract kind | immutable-snapshot-stage      |
| Visibility    | public                        |
| Owner         | `docs/tool-store-contract.md` |

## Purpose

Fix the store grammar, identities, selection rule, whole-stage acceptance, restoration, failure behavior, and garbage-collection protection implemented by c0dev.

## Store Grammar

```text
/tools/
  opt/<tools-id>/
    .c0dev-complete
    .c0dev-accepted-from      # accepted snapshots only
    .c0dev-stage-sha256       # accepted snapshots only
    .cargo/bin/
    .rustup/
    .local/
  pins/<folder-id>.pin
  tmp/<tools-id>.partial
  tmp/<build-id>.next
```

```text
complete-snapshot := /tools/opt/<64-lower-hex> containing .c0dev-complete
build-snapshot    := complete-snapshot whose id is TOOLS_BUILD_ID
accepted-snapshot := complete-snapshot containing accepted-from and stage-sha256
selected-snapshot := complete-snapshot named by the valid checkout pin, else build-snapshot
runtime-mount     := selected-snapshot mounted at /tools/current read-only
writable-stage    := complete per-instance OverlayFS upper for configured home overlays
```

The runtime receives the selected volume subpath only. It does not receive `/tools`, pins, temporary paths, or other snapshots.

## Identity

`TOOLS_BUILD_ID` is the existing comment-stripped hash of `Dockerfile.base` and `Dockerfile.tools`.

An acceptance snapshots the complete merged overlay archives while the runtime is paused. `stage-sha256` hashes the ordered archive digests. The accepted ID is:

```text
sha256("c0-tools-accept-v1\n" + parent-tools-id + "\n" + stage-sha256 + "\n")
```

The archive digest includes file content and archive metadata. It identifies the captured snapshot operation; it is not claimed to be a reproducible package lock.

## Roles And Authority

| Role             | Network | Read authority                                | Write authority                                   |
| ---------------- | ------- | --------------------------------------------- | ------------------------------------------------  |
| Runtime          | Normal  | Selected snapshot RO; host mounts; own stage  | Container layer, host RW mounts, own stage        |
| Overlay helper   | None    | Selected lower and overlay state              | Runtime mount namespace and overlay upper/work    |
| Snapshot helper  | None    | Paused runtime merged overlay                 | Host-owned temporary archive stream only          |
| Publisher        | None    | Parent snapshot and snapshot archives         | `/tools/{opt,tmp,pins}` through fixed host code   |
| Collector        | None    | Pins and active container labels              | Unprotected complete snapshots and temporary data |

The runtime never receives the Docker socket, tools-volume write access, `SYS_ADMIN`, or publication metadata. The publisher uses a read-only root filesystem, no network, dropped capabilities plus the documented ownership/DAC capabilities needed to copy and normalize the snapshot, and no runtime mount-namespace authority.

## Stage Contract

The stage is the entire upper, not a classifier result. `c0 tools --detail` exposes observable entries as:

| Status | Meaning                                                    |
| ------ | ---------------------------------------------------------  |
| `A`    | Upper entry has no corresponding selected-lower entry      |
| `M`    | Upper non-directory shadows a selected-lower path          |
| `D`    | Overlay whiteout hides a selected-lower path               |
| `O`    | Opaque upper directory hides selected-lower directory data |

Default `c0 tools` may collapse added paths to a count but must show the total stage disposition and the commands affecting it. `--detail` must list all entries observable by the checker. Neither display mode decides whether a path is payload or state.

## Accept Transition

```text
selected + staged
  -> pause runtime
  -> snapshot merged configured overlays
  -> resume runtime
  -> copy selected to /tools/tmp/<accepted-id>.partial
  -> replace configured paths with merged archives
  -> record parent and stage digest
  -> normalize ownership
  -> write .c0dev-complete last
  -> move to /tools/opt/<accepted-id>
  -> update checkout pin
  -> remove runtime
  -> clear complete upper/work state
  -> recreate with accepted-id mounted RO
```

Acceptance is a host authorization event. It includes every path in the merged configured overlays, including direct non-XDG runtime state. A complete existing accepted ID is reused; an existing incomplete target is never replaced implicitly.

## Restore Transition

```text
selected + staged
  -> retain selected pin
  -> remove runtime
  -> clear complete upper/work state
  -> recreate with the same selected-id mounted RO
```

Restore is intentionally destructive and provides no c0 recovery for the discarded upper. Host paths outside the overlay volume are unaffected.

## Build Transition

`c0 build` remains separate. It creates `/tools/tmp/<TOOLS_BUILD_ID>.partial`, extracts the builder-created payload, writes completeness last, publishes or safely stages a force rebuild, and pins the complete build ID after successful image construction. `c0 tools` never invokes this transition.

## Selection And Protection

The checkout pin is both the selection ref and a garbage-collection claim. A running container label protects the exact snapshot mounted into that runtime. Resolution falls back to `TOOLS_BUILD_ID` when no valid complete pin exists; malformed or incomplete selections produce a warning.

```text
protected := valid checkout pins union running-container tools labels
```

Collection may delete only complete 64-hex snapshots absent from `protected`. Build failure never updates the pin or triggers success-path collection.

## Failure Contract

- Snapshot failure resumes the paused runtime and leaves stage, pin, and selected snapshot unchanged.
- Publisher failure leaves the parent selected and the upper intact.
- Pin update occurs only after the accepted snapshot is complete.
- Stage clearing occurs only after successful publication and pin update.
- Failure after publication but before clearing may leave the new snapshot selected with the old upper still staged; a later explicit accept or restore resolves it.
- Runtime recreation failure leaves the complete selected snapshot and persistent stage storage available for diagnosis.
