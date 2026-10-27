---
doc-graph: "When there is an intention to amend this document, first Adhere to [dc-doc-goals]; otherwise, do not modify."
---

# c0dev Goals

## Purpose

Define the durable outcomes and priority relationships that make c0dev a useful, inspectable, and constrained development guest for human and autonomous coding work.

## Goals

| ID      | Priority | Desired outcome                           | Success criterion                                                                                                                     |
| ------- | -------- | ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `C0-G1` | highest  | Preserve the runtime security boundary    | The long-running guest remains non-privileged, uses the project seccomp profile, and never receives tool-store publication authority  |
| `C0-G2` | highest  | Keep canonical tools immutable at runtime | Canonical binaries and resources are shared, versioned, and mounted read-only; neither `dev` nor `c0 root` can modify them            |
| `C0-G3` | high     | Make runtime tool writes durable          | Native writes beneath overlaid tool-home paths survive recreation in one per-instance writable stage                                  |
| `C0-G4` | high     | Keep build and stage operations distinct  | `c0 build` constructs defaults; `c0 tools` only inspects, accepts, or restores runtime-written state                                  |
| `C0-G5` | high     | Keep tool-state decisions simple          | One command shows the stage and one explicit subcommand either accepts all of it or restores the selected snapshot                    |
| `C0-G6` | high     | Preserve publication separation           | Runtime updaters cannot write the tools volume; only a host-launched networkless publisher can create a complete accepted snapshot    |
| `C0-G7` | medium   | Retain practical guest administration     | Operators can use `c0 root` and `apt` inside the existing constrained runtime without gaining write access to canonical tools         |
| `C0-G8` | medium   | Make behavior locally auditable           | A reader can map every command and process variant to source, identity, capabilities, mounts, network access, state, and verification |
| `C0-G9` | medium   | Preserve reproducible defaults            | Dockerfile inputs identify the build toolset; accepted runtime state receives a separate immutable snapshot identity                  |

## Goal Relationships

`C0-G1` and `C0-G2` are co-equal foundations: a writable selected snapshot or privileged long-running guest invalidates the containment model. `C0-G3` through `C0-G6` make the writable upper deliberate without turning `c0 tools` into a second build system. `C0-G7` preserves the existing administrative lane. `C0-G8` and `C0-G9` make the selected build or accepted snapshot reviewable.

## Success Criteria

- Runtime `dev` and `c0 root` see only the selected `/tools/opt/<TOOLS_ID>` subpath at `/tools/current:ro`.
- Native installers and self-updaters can change the per-instance upper but cannot publish or alter any complete snapshot.
- `c0 tools` summarizes the upper; `c0 tools --detail` lists every affected path.
- `c0 tools accept` snapshots the complete merged overlay, writes a new completeness-last immutable toolset, updates the checkout pin, clears the upper, and recreates the runtime.
- `c0 tools restore` clears the complete upper without changing the selected toolset and recreates the runtime.
- Failed acceptance leaves the selected snapshot and writable upper recoverable.
- `c0 build` and `c0 build -f` remain the only tool construction paths.

## Priorities And Tradeoffs

Runtime containment outranks in-place mutation of a complete snapshot. Explicit whole-stage acceptance outranks inferred path policy because c0 cannot reliably distinguish a new tool payload from a tool's native support state. A brief controlled runtime recreation outranks live OverlayFS lower replacement because already-mounted lower layers cannot be swapped safely and generically.

## Non-Goals

- Preventing the owning macOS user or Docker operator from changing the environment.
- Persisting ad hoc `apt` mutations across destructive guest recreation.
- Updating the executable image of an already-running process without restarting that process.
- Inferring whether an arbitrary staged path is executable payload, authentication, cache, log, configuration, or generated data.
- Treating `c0 tools` as another installer, package manager, or build command.
- Treating c0dev as a multi-tenant or hostile-host security boundary.
