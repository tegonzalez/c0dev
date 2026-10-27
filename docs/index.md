---
doc-graph: "When there is an intention to amend this document, first Adhere to [dc-doc-index]; otherwise, do not modify."
---

# c0dev Authority Index

## Purpose

Route maintainers to the owners of this development-environment tool's outcomes, public behavior, architecture, negative guidance, tools-storage seam, security interpretation, native tool compatibility, and admitted residuals. This is the single root index for that work-product scope; it admits no component subtree.

## Terminology

| Term                      | Meaning                                                                                            |
| ------------------------- | -------------------------------------------------------------------------------------------------- |
| Authority ID              | Stable local routing identity for one owner.                                                       |
| Priority                  | Declared integer used only for competing claims on the same question, scope, and baseline.         |
| Current baseline          | Realized launcher, Docker, toolchain, and storage model described by the owners.                   |
| Hardened release baseline | Security requirements whose realization and evidence must be established before release clearance. |

## Authority Basis

| Authority ID | Priority | Class                 | Surface                                        | Scope                                                   | Dimensions                                                                                        | Disposition                                                    | Closure                                       | Expansion                          |
| ------------ | -------- | --------------------- | ---------------------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- | --------------------------------------------- | ---------------------------------- |
| A-01         | 90       | `dc-doc-goals`        | [Goals](goals.md)                              | Cross-change product outcomes                           | Least authority, host safety, durability, immutable defaults, private data, secure releases       | Governs intended outcomes                                      | Outcomes before behavior and evidence         | Outcome-owner admission            |
| A-02         | 60       | `dc-doc-spec`         | [Specification](spec.md)                       | Current behavior and required hardened release baseline | Public commands, lifecycle, mounts, security requirements, release refusal and evidence           | Owns consumer-visible behavior and release-security criteria   | Goals, behavior, seam contract, evidence      | Behavior-owner admission           |
| A-03         | 45       | `dc-doc-design`       | [Design](design.md)                            | Current tool architecture                               | Modules, seams, mechanisms, rationale, realization limits                                         | Owns mechanism; cannot weaken required behavior                | Behavior, mechanism, contract, evidence       | Design-owned module/seam admission |
| A-04         | 95       | `dc-doc-constraints`  | [Constraints](constraints.md)                  | Cross-module author guidance                            | Forbidden authority, exposure, unsafe effects, acquisition, secrets, release and cleanup patterns | Owns negative guidance                                         | Constraint before proposed mechanism          | Root constraint admission          |
| A-05         | 60       | `dc-doc-contract`     | [Tools-store contract](tool-store-contract.md) | Current M-05 / SM-02 seam                               | Exact identities, storage, stage, publication, restoration, reference protection                  | Owns formal store shape                                        | Specification, contract, mechanism, evidence  | Same-seam contract admission       |
| A-06         | 60       | `dc-doc-technical`    | [Security model](security-model.md)            | Current trust interpretation                            | Process privilege/exposure, host and credential boundaries, input trust, assurance limits         | Explains controls; release law remains specification-owned     | Requirement, trust interpretation, evidence   | Security-reference admission       |
| A-07         | 60       | `dc-doc-technical`    | [Tool compatibility](tool-compatibility.md)    | Current native tool behavior                            | Payload/state locations, activation, update and acceptance consequences                           | Explains tool behavior; no alternate installer or release gate | Specification, store, tool behavior, evidence | Native-compatibility admission     |
| A-08         | 20       | `dc-doc-known-issues` | [Known issues](known-issues.md)                | Finite current residuals                                | Restatement, owner, disposition, retirement                                                       | Records limits; never waives requirements or grants readiness  | Governing owner before residual               | Finite-residual admission          |

Goals, specification, design, and constraints use explicit priorities reflecting their outcome, behavior, mechanism, and negative-guidance responsibilities. Contract and technical owners are explicitly assigned 60 for their noncompeting dimensions; the residual register is explicitly assigned 20 because it cannot redefine product criteria. The same-question comparison first establishes scope and current/intended baseline applicability; a higher integer governs correction of the lower owner, and equal competing integers require explicit owner resolution. Recency, branch provenance, implementation, passing tests, and file location confer no additional authority. Live requester instructions retain their instruction-level precedence.

## Query Routes

| Question                                                   | Kind    | Ordered owners                                                   | Missing-input behavior                                                    |
| ---------------------------------------------------------- | ------- | ---------------------------------------------------------------- | ------------------------------------------------------------------------- |
| What outcome governs a design tradeoff?                    | direct  | Goals                                                            | Report missing outcome meaning                                            |
| What does a command expose or preserve?                    | direct  | Specification                                                    | Gate on missing behavior                                                  |
| How is behavior produced?                                  | derived | Specification → Design → relevant contract                       | Gate on first missing owner                                               |
| Which permissions and host surfaces are justified?         | derived | Goals → Specification → Constraints → Security model → evidence  | Missing necessity or native proof is not a security pass                  |
| Which host data survives lifecycle or tools operations?    | derived | Specification → Tools-store contract → Tool compatibility        | Preserve uncertain storage rather than infer deletion authority           |
| May a payload be selected, replaced, or collected?         | derived | Specification → Tools-store contract                             | Require complete identity, ownership, and references                      |
| What blocks a release for vulnerabilities or secrets?      | direct  | Specification, Release Security and Private Data                 | Unknown content, applicable findings, or missing evidence block clearance |
| Which current security controls are actually demonstrated? | derived | Specification → Security model → source and independent evidence | Distinguish source configuration from observed effects                    |
| Which finite residual affects current behavior?            | direct  | Governing specification/contract → Known issues                  | A residual cannot waive its owner's requirement                           |
| Is an integrated result acceptable?                        | derived | Goals → Specification → relevant contract → independent evidence | Mechanical success alone is insufficient                                  |

## Durable Boundary

Goals own outcomes; the specification owns required behavior and release-security acceptance; constraints own focused forbidden patterns; the contract owns exact tools-storage semantics; design owns mechanisms; references explain current facts; known issues record finite subordinate limits. README is onboarding and evidence consumption, not a competing release policy. Shared SWE and graph procedures govern authoring and evaluation, not c0dev's security choices; project-specific requirements stay here.

Implementation and tests provide realization and regression evidence. They cannot redefine a security requirement to make current behavior pass. Imported documents must be reconciled with the current owners and implemented surface before they direct future work. An unevidenced intended requirement remains explicit rather than being presented as delivered protection.
