---
doc-graph: "When there is an intention to amend this document, first Adhere to [dc-doc-known-issues]; otherwise, do not modify."
---

# c0dev Known Issues

## Purpose

Record finite current behavior limits against their specification or contract without redefining security requirements or sequencing implementation work.

## Orientation

An admitted residual explains current availability; it does not waive the [release-security gate](spec.md#release-security). The security reference separately identifies current source evidence and missing assurance without claiming deployed failures.

## Terminology

| Term              | Meaning                                                                                |
| ----------------- | -------------------------------------------------------------------------------------- |
| Accepted tradeoff | Deliberate current design limit retained within its stated scope.                      |
| Verification gap  | Finite missing implementation or verification assurance against an owning requirement. |
| Seed              | `unseeded` until one separately identified Change receives the residual.               |

## Register

| id    | datetime             | kind              | restatement                                                                                                            | owner                                 | seed     | disposition                                                                                                                         | retirement                                                                                                                 |
| ----- | -------------------- | ----------------- | ---------------------------------------------------------------------------------------------------------------------- | ------------------------------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| KI-01 | 2026-10-26T01:23:53Z | accepted-tradeoff | Ordinary stop/replacement does not preserve arbitrary guest-root filesystem changes.                                   | [Specification](spec.md#model)        | unseeded | Preserve declared host mounts and home overlays; put durable system defaults in build inputs.                                       | A separately specified persistence surface changes this lifetime.                                                          |
| KI-02 | 2026-10-26T01:23:53Z | accepted-tradeoff | Current macOS host bind semantics do not provide the required writable OverlayFS upper.                                | [Specification](spec.md#host-mounts)  | unseeded | Keep upper/work in positively identified Linux workspace storage and ordinary configuration/data in declared host mounts.           | Supported host storage supplies and verifies the required OverlayFS behavior.                                              |
| KI-03 | 2026-10-26T01:23:53Z | verification-gap  | Whole-stage tools capture does not establish exclusion of credentials or private native state from accepted artifacts. | [Specification](spec.md#private-data) | unseeded | Treat path display and archive hashes as insufficient secret-exclusion evidence; do not clear a release containing private content. | Exact publication and release evidence establishes required private-data exclusion across supported writers and artifacts. |

## Boundaries

The register grants no acceptance of vulnerable or secret-bearing releases and no authority to retire supported commands or durable mounts. Task-local findings, proposed mechanisms, and work schedules retain their own bounded owners. Source-only observations are not proof of an exploit or of complete security conformance.
