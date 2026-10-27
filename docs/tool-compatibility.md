---
doc-graph: "When there is an intention to amend this document, first Adhere to [dc-doc-technical]; otherwise, do not modify."
---

# c0dev Tool Compatibility

## Purpose

Describe how tools using native home-directory layouts interact with the build payload, runtime OverlayFS stage, host XDG paths, and explicit acceptance.

## General Contract

Non-apt tools installed by `Dockerfile.tools` run as `dev` in `/home/dev`. c0 packs the complete builder-created `.local`, plus `.cargo/bin` and `.rustup`; future supporting files under `.local/share` therefore require no additional extraction allowlist.

At runtime, the selected `.local` is the read-only lower and the per-instance stage is the upper. A tool may create, replace, or delete any native path beneath merged `~/.local`. This behavior does not alter the selected snapshot.

`c0 tools` does not decide whether a change is payload or state. An explicit acceptance approves the complete merged overlaid path; restoration discards the complete upper. Tools requiring finer semantic separation must honor the configured XDG host paths themselves.

## Environment

| Variable          | Runtime value               | Authority                                  |
| ----------------- | --------------------------- | ------------------------------------------ |
| `TOOLS_PREFIX`    | `/tools/current`            | Selected immutable snapshot                |
| `XDG_CONFIG_HOME` | `/home/dev/.config`         | Host bind                                  |
| `XDG_CACHE_HOME`  | `/home/dev/.cache`          | Host bind                                  |
| `XDG_DATA_HOME`   | `/home/dev/.local-rw/share` | Host `.local/share`                        |
| `XDG_STATE_HOME`  | `/home/dev/.local-rw/state` | Host `.local/state`                        |
| `CARGO_HOME`      | `/home/dev/.cache/cargo`    | Host cache                                 |
| `UV_CACHE_DIR`    | `/home/dev/.cache/uv`       | Host cache                                 |
| `RUSTUP_HOME`     | `/tools/current/.rustup`    | Selected immutable snapshot; updates off   |

Tools honoring XDG write common state directly to visible host folders. Tools hardcoding `~/.local` write the stage and appear in `c0 tools`.

Executable lookup uses merged `/home/dev/.local/bin`, not the lower path beneath `TOOLS_PREFIX`; an upper replacement therefore becomes effective while an unchanged path still resolves from the selected lower.

## Current Tool Matrix

| Tool class                     | Build location                      | Expected runtime writes                                      | Update disposition                                                                |
| -----------------------------  | ----------------------------------- | ------------------------------------------------------------ | ---------------------------------------------------                               |
| uv/uvx                         | `.local/bin`, `.local/share/uv`     | Host uv cache; Python bytecode may enter stage               | Native changes remain staged until accept/restore                                 |
| Cursor Agent and Factory Droid | `.local/bin`, `.local/share`        | Config/cache when honored; native updater files may stage    | Inspect with `c0 tools`                                                           |
| Devin CLI                      | `.local/bin`, `.local/share/devin`  | Logs and installation state may enter stage                  | Whole-stage semantics apply                                                       |
| Semgrep                        | `.local/bin`, uv-managed resources  | Cache and generated Python bytecode                          | Whole-stage semantics apply                                                       |
| Rustup and Cargo-built tools   | `.rustup`, `.cargo/bin`             | Cargo/registry cache redirected to host                      | Defaults change through `c0 build`; `.local` stage does not cover these paths yet |
| Bun globals                    | Runtime image global install        | Tool-specific host config/cache                              | Persistent default changes require `c0 build`                                     |
| apt packages                   | Runtime image or runtime layer      | System state                                                 | `c0 root` changes are not tool snapshots                                          |

## Display Semantics

`A`, `M`, `D`, and `O` describe filesystem relationships only. In particular, `A` can mean a new executable, dependency, log, credential, database, or bytecode file. No status implies safety or canonical eligibility.

The default display collapses added paths because native runtimes can generate thousands of files. `--detail` is the authority for the exact observable path set before accept or restore.

## Acceptance Consequences

- Accepted content becomes part of a new read-only selected snapshot.
- A fresh empty upper is mounted after recreation, so later native writes copy up again.
- The parent build or accepted snapshot remains immutable.
- Accepted snapshots record parent and archive digest but do not claim reproducible source provenance.
- Direct non-XDG credentials or logs can be accepted; users must inspect `--detail` before authorizing when this matters.

## Adding A Tool

A new default non-apt tool belongs in `Dockerfile.tools` and must install as `dev`. If it writes anywhere under `.local`, no extraction-list edit is required. Its documentation should identify whether it honors XDG or writes direct native state so operators understand what will appear in the stage.
