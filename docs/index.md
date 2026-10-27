---
doc-graph: "When there is an intention to amend this document, first Adhere to [dc-doc-index]; otherwise, do not modify."
---

# c0dev Authority Index

## Purpose

Route readers and implementing agents to the durable owners of c0dev outcomes, public behavior, architecture, constraints, tool-store law, security boundaries, tool eligibility, and admitted residuals without duplicating those owners here.

## Authority Basis

| Handle                                        | Class                 | Governed scope                                                                 | Priority                                                        |
| --------------------------------------------- | --------------------- | ------------------------------------------------------------------------------ | --------------------------------------------------------------- |
| [Project goals](goals.md)                     | `dc-doc-goals`        | Desired outcomes, priorities, success criteria, and non-goals                  | Sole owner for product alignment                                |
| [Product specification](spec.md)              | `dc-doc-spec`         | Public commands, observable behavior, state locations, diagnostics, boundaries | Sole owner for consumer-visible behavior                        |
| [Architecture design](design.md)              | `dc-doc-design`       | Modules, process variants, seams, mechanisms, decisions, and rationale         | Sole owner for architecture                                     |
| [Constraints](constraints.md)                 | `dc-doc-constraints`  | Forbidden architectures, detection signals, and replacements                   | Sole owner for reusable negative guidance                       |
| [Tool-store contract](tool-store-contract.md) | `dc-doc-contract`     | Store grammar, permissions, transactions, publication, rollback, and GC        | Sole owner for exact tool-store mechanics                       |
| [Security model](security-model.md)           | `dc-doc-technical`    | Threat boundaries, privilege matrix, attack surface, and operating controls    | Sole owner for security interpretation                          |
| [Tool compatibility](tool-compatibility.md)   | `dc-doc-technical`    | Per-tool payload, mutable state, update route, and verification contract       | Sole owner for canonical-tool eligibility                       |
| [Known issues](known-issues.md)               | `dc-doc-known-issues` | Admitted finite product and verification residuals                             | Sole owner for admitted residuals; never behavior or scheduling |

No class, file age, implementation behavior, test result, path depth, or prose confidence grants priority beyond this table. A missing owner is a gate; nearby documentation is not a substitute.

## Query Routes

| Question                                                      | Kind    | Ordered owners                                     | Missing-input behavior                       |
| ------------------------------------------------------------- | ------- | -------------------------------------------------- | -------------------------------------------- |
| What outcome should c0dev optimize?                           | direct  | Project goals                                      | Report the missing goals owner               |
| What does a command accept, guarantee, reject, or diagnose?   | direct  | Product specification                              | Report the missing specification owner       |
| How is specified behavior produced?                           | derived | Product specification -> Architecture design       | Gate on the first missing owner              |
| Is an implementation or privilege pattern forbidden?          | direct  | Constraints                                        | Report the missing constraint owner          |
| Is one tool-store transition legal?                           | direct  | Tool-store contract                                | Gate before executing the transition         |
| What privilege does one process receive?                      | direct  | Security model                                     | Gate before making a security claim          |
| May a tool be published into the canonical read-only store?   | derived | Tool-store contract -> Tool compatibility          | Reject eligibility until both owners resolve |
| Which accepted residual currently affects an owning contract? | direct  | Known issues                                       | Report that no admitted residual exists      |
| Is the integrated result acceptable for its intended purpose? | derived | Project goals -> Product specification -> Evidence | Mechanical output alone is insufficient      |

## Durable Boundary

Only the guarded Markdown documents in the Authority Basis own surviving product meaning. Plans, progress, implementation gaps, test matrices, transcripts, patches, branches, and command output are temporal evidence. They may consume this authority but never become durable reference targets.

## Consumer Questions

Use [README](../README.md) for onboarding and common commands. Use this index for every documentation ownership question. Active implementation order, task status, and transient verification evidence have no durable owner here.
