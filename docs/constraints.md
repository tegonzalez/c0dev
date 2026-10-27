---
doc-graph: "When there is an intention to amend this document, first Adhere to [dc-doc-constraints]; otherwise, do not modify."
---

# c0dev Constraints

## Purpose

Record the forbidden architectures, repeated failure modes, detection signals, and replacement guidance required by authors implementing, extending, or reconsidering c0dev.

## Audience

This document is for authors changing the runtime, build pipeline, tool lifecycle, storage layout, host mounts, or security profile.

## Constraints

### `C0-C001` Writable Canonical Store In Runtime

Mounting complete tools read-write in the runtime lets a compromised `dev` or `c0 root` process replace shared executables and resources. Detect any runtime mount of a selected prefix without `ro`. Mount only `/tools/opt/<TOOLS_ID>` at `/tools/current:ro`; runtime changes belong in the OverlayFS upper.

### `C0-C002` Networked Installer With Whole-Store Write Access

Giving runtime updater code the tools volume read-write lets an upstream compromise alter complete snapshots, pins, or other workspaces. Detect any networked runtime or updater with shared-volume write access. Runtime code writes only the upper; a fixed networkless host publisher alone receives tools-volume write authority after explicit acceptance.

### `C0-C003` In-Place Published Tool Mutation

Updating a complete selected prefix in place produces mixed versions and exposes partial state. Detect writes beneath a path containing `.c0dev-complete`. Acceptance must copy the selected snapshot to a new 64-hex identity, replace overlaid paths in the unpublished copy, write completeness last, and update the checkout pin afterward.

### `C0-C004` Tools Command As A Second Build System

Making `c0 tools` rebuild Dockerfiles or invoke a second installer path conflates construction with writable-stage disposition. Detect build flags, selectors, or package-manager orchestration beneath `c0 tools`. Keep construction in `c0 build [-f]`; reserve `c0 tools` for display, acceptance, and restoration.

### `C0-C005` Root Tool Installation

Installing language and assistant tools as root during the image tools stage expands authority and hides ownership defects. Detect builder-created payload owned by UID 0. Run non-apt Dockerfile tool installers after `USER dev`; runtime `c0 root` remains constrained and can write only its stage.

### `C0-C006` Installer Publication Authority

Letting a runtime installer update pins or completeness metadata allows fetched code to self-approve. Detect guest access to tools metadata or the Docker socket. Only explicit host `c0 tools accept` may invoke the fixed networkless publisher.

### `C0-C007` Unresolved Latest In Canonical Identity

Building `latest` under a stable Dockerfile hash can produce different payloads for identical `TOOLS_BUILD_ID` inputs. Detect mutable build selectors when strict reproducibility is claimed. Accepted snapshots receive independent identities, but this does not make the original build reproducible.

### `C0-C008` Hidden Stage Scope

Classifying only packaged-path overrides hides upper-only files that acceptance or restoration will also affect. Detect counters without a complete path view. `c0 tools --detail` must enumerate every staged non-directory entry, deletion marker, opaque directory, and added directory that the operation can observe.

### `C0-C009` Guest Mount Or Publication Capability

Granting `SYS_ADMIN`, Docker socket access, namespace entry, or store publication to the long-running runtime defeats the established boundary. Detect those authorities on the runtime container or its processes. Overlay mount and snapshot operations may use only the documented short-lived, networkless host-launched helper; publication remains a separate networkless process without mount-namespace authority.

### `C0-C010` Hidden Host Orchestrator Delta

Special-casing `bin/` as a read-only bind or OverlayFS upper so guest writes never hit the host checkout hides `c0` mutation from the same git working tree that guards the rest of the tree. Detect `:ro` or an overlay on `/home/dev/bin` while sibling host folders remain read-write binds. Mount `bin/` read-write like `.claude`; a guest edit of tracked `bin/c0` is a host git delta.

### `C0-C011` Aggressive Garbage Collection

Deleting a hash referenced by a valid checkout pin or running-container label breaks selected commands. Detect GC reachability that ignores either protection source. Retain pinned and active snapshots; incomplete non-selected paths may be cleaned separately.

### `C0-C012` Canonical Integrity Claimed From PATH Alone

Placing a mutable user directory before canonical binaries silently changes the effective tool while the store remains intact. Detect undocumented PATH precedence or mutable shims presented as canonical integrity. Prefer canonical paths by default and make user-channel overrides explicit and diagnosable.

### `C0-C013` Persistent Ad Hoc Runtime Package Drift

Treating `c0 root` package changes as reproducible state makes destructive recreation surprising and may invalidate the built runtime ABI. Detect claims that live `apt` changes alter image or toolset identity. Treat them as runtime-layer administration; persistent OS changes belong in the runtime build inputs.
