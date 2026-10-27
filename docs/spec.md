---
doc-graph: "When there is an intention to amend this document, first Adhere to [dc-doc-spec]; otherwise, do not modify."
---

# c0dev Specification

## Purpose

Define the public behavior of the host launcher, Docker development guest, tools storage, and durable workspace. Must states a requirement; may states permitted variation. Command and storage descriptions identify the current branch's behavior. Security requirements identify the required hardened release baseline; this document does not establish their implementation or a completed security clearance. Current source observations and unresolved assurance limits appear in the [security model](security-model.md#assurance-limits).

## Terminology

| Term                           | Meaning                                                                                                                                                            |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Workspace                      | Mode and real working folder owning durable host mappings and writable home storage.                                                                               |
| Runtime instance               | Mode, build, and real working folder identifying a Docker guest.                                                                                                   |
| Build identity                 | Recipe and canonical resolved release selections identifying shared build artifacts.                                                                               |
| Selected payload               | Complete immutable tools content named by Docker publication or an actual runtime mount.                                                                           |
| Tools stage                    | Configured writable tool-home upper; launcher upper is separate.                                                                                                   |
| Release candidate              | Exact source and all artifacts proposed for distribution, including images and embedded software.                                                                  |
| Known applicable vulnerability | A disclosed vulnerability affecting content or a supported execution path of the exact release candidate, with applicability unresolved until evidenced otherwise. |

## Model

Build artifacts are shared for equivalent mode, recipe, and resolved software selections; runtime instances additionally include working-folder identity. Docker images, labels, containers, mounts, and volumes supply discovery. No persistent checkout pin, saved selector, or volume-reference file supplies runtime selection.

The guest sees only its selected tools payload at `/tools/current:ro`. Persistent tool and launcher uppers allow native writes without changing the selected lower. Declared host configuration, cache, and project mounts remain durable. Ordinary stop removes workspace runtime containers while preserving host mounts and home-overlay storage; a later start creates from the currently published build. Existing matching runtime instances are reused by start. Stopped or recovery containers that remain in Docker still protect their referenced content.

## Public Surface

| ID   | Kind / visibility / use                   | Shape                                                                           | Trigger                                                  | Refusal or failure                                                                                   | Derivation                                                      |
| ---- | ----------------------------------------- | ------------------------------------------------------------------------------- | -------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| S-01 | Command / public / callable               | `c0 build [-f]`                                                                 | Construct or force rebuild shared artifacts              | Missing prerequisites, resolution, build, provenance, or validation failure                          | [Build path](design.md#build-path)                              |
| S-02 | Command / public / callable               | `c0 tools`                                                                      | Inspect tools stage                                      | Missing or invalid running overlay                                                                   | [Stage contract](tool-store-contract.md#stage-contract)         |
| S-03 | Command / public / callable               | `c0 tools --detail`                                                             | Inspect full observable stage                            | Same tools-stage prerequisites                                                                       | [Stage contract](tool-store-contract.md#stage-contract)         |
| S-04 | Command / public / callable               | `c0 tools accept`                                                               | Publish complete staged tools                            | Capture, validation, or publication failure                                                          | [Accept transition](tool-store-contract.md#accept-transition)   |
| S-05 | Command / public / callable               | `c0 tools restore`                                                              | Discard configured tools upper                           | Different published selection or shared/unsafe storage                                               | [Restore transition](tool-store-contract.md#restore-transition) |
| S-06 | Commands / public / callable              | `c0 start [--least-privilege]`, `stop`, `restart [--least-privilege]`, `status` | Manage or observe workspace runtime                      | Unavailable Docker, ambiguous ownership, conflicting build/storage, invalid mounts or security       | [Lifecycle](design.md#runtime-mount-path)                       |
| S-07 | Commands / public / callable              | `c0 sh`, `c0 root`, `c0 ssh [-Y] [command...]`, `c0 ssh --keygen`               | Attach or explicitly prepare SSH keys                    | Missing/invalid runtime or native transport/key failure                                              | [Attachments](#attachments)                                     |
| S-08 | Storage / public / read-only              | Selected `/tools/current`                                                       | Guest tool execution                                     | Missing/incomplete payload or wrong mount                                                            | [Store grammar](tool-store-contract.md#store-grammar)           |
| S-09 | Storage / public / read/write             | `/run/c0/overlay-state` through configured uppers                               | Native tool and launcher writes                          | Unsafe or ambiguous workspace storage                                                                | [Stage contract](tool-store-contract.md#stage-contract)         |
| S-10 | Storage / public / declared access        | Host configuration, cache, auth, Git settings, and project mappings             | Guest development                                        | Missing, redirected, wrong-mode, or conflicting required mapping                                     | [Host mounts](#host-mounts)                                     |
| S-11 | Command / public / callable               | `c0 clean [-a]`                                                                 | Collect rebuildable tools caches                         | Any container reference; whole-store removal also refuses published images and unknown retained data | [Protection](tool-store-contract.md#selection-and-protection)   |
| S-12 | Command / public / callable               | `c0 logs [svc]`                                                                 | Read native service logs                                 | Missing runtime or native log failure                                                                | [Host router](../bin/c0)                                        |
| S-13 | Command / public / callable               | `c0 orca [start\|stop\|status]`                                                 | Observe or control guest Orca; bare invocation is status | Missing runtime/executable or native service failure                                                 | [Host router](../bin/c0)                                        |
| S-14 | Command / public / callable               | `c0 cp-term`                                                                    | Explicit system terminfo transfer                        | Host extraction, transfer, or compilation failure                                                    | [Host router](../bin/c0)                                        |
| S-15 | Command / public / callable               | `c0 seccomp-upgrade [--dry-run]`                                                | Resolve and inspect or adopt upstream seccomp            | Acquisition, content, or write validation failure                                                    | [Host router](../bin/c0)                                        |
| S-16 | Command / public / callable               | `c0 help`, `--help`, `-h`                                                       | Show implemented interface                               | Native launcher initialization failure                                                               | [Host router](../bin/c0)                                        |
| S-17 | Release requirement / public / gating     | Exact candidate and security evidence                                           | Any project release                                      | Known applicable vulnerability, secret, or unresolved coverage                                       | [Release security](#release-security)                           |
| S-18 | Security requirement / public / governing | Runtime, host-command, input, secret, and network boundaries                    | Construction, execution, publication, and cleanup        | Unsupported authority or missing required assurance                                                  | [Containment](#containment), [private data](#private-data)      |

## Invariants

- Routine runtime execution is non-privileged and unprivileged; explicit guest administration remains within the guest's declared restrictions.
- The guest has no Docker socket, tools-store writer, host namespace, or publication authority.
- Tools acceptance preserves the running guest, its fixed mounted lower, and its writable stage; restore resumes the same container after clearing only configured tool state.
- Host mounts and launcher state survive tools disposition. Ordinary stop removes the disposable container layer, not declared durable host data or home-overlay storage.
- Unknown ownership, storage lineage, required security state, or artifact references cannot authorize destructive effects.
- A passing build, functional test, or completeness marker is not release-security clearance.

## Contracts

The [tools-store contract](tool-store-contract.md) owns exact identity, storage grammar, stage, publication, restoration, and protection rules. The [security model](security-model.md) explains trust premises and current assurance limits. The [tool compatibility reference](tool-compatibility.md) identifies native payload and state locations. [README](../README.md#commands) provides operator workflows; the launcher help remains the implemented command inventory.

## Semantics

### Build

Build resolves current supported releases once, captures the canonical manifest, and binds both tools and runtime construction to those selections. Changed resolved inputs change identity. Cached artifacts require matching provenance and validation. Force rebuild changes cache/extraction disposition without granting permission to overwrite referenced content or replace a running guest. Current core includes Rust/Cargo-built tools, managed Node/Python and package managers, Semgrep, and assistant CLIs; no `c0 pkg` or named-environment facade is supplied by this branch.

### Tools Disposition

Inspection is read-only. Acceptance publishes the whole configured tools stage as a new immutable payload and derived shared runtime artifact; current processes keep their mounted lower until a later lifecycle replacement. Restoration discards only configured tool upper/work state and resumes the same guest; it refuses a resolved selection mismatch or a stage shared with another retained container. Its current publication comparison is conditional on successful initial recipe-image inspection, as the contract describes; a failed initial inspection can skip that comparison and does not satisfy the hardened fail-closed requirement. Exact transitions belong to the contract.

### Host Mounts

Declared host mounts are supported durable configuration and data surfaces. Their source, destination, access mode, and feature purpose must be explicit; successful guest write access intentionally includes those host effects. Lifecycle and cleanup must preserve unrelated files and cannot recursively purge host configuration, caches, projects, auth, or home-overlay storage.

New runtimes use a read-only host launcher lower with a separate persistent guest launcher upper. Host Git configuration, entrypoint, and overlay-control inputs are read-only mounts. Supported legacy layouts remain separately classified; recognition of a retained legacy guest is not proof that it meets the hardened release baseline. Broad account-home, daemon-control, and unrelated host mounts are outside the required feature surfaces.

### Attachments

Ordinary shell and SSH execution use `dev`; explicit `c0 root` uses guest UID 0 without obtaining host root or publication authority. Host SSH uses loopback publication and selected test/operator keys. Credential-file values are literal input, not shell code. Attachments restore these values only in the selected guest process environment; they do not become transport argv or host launcher/control variables. Ordinary environment names, quoting, empty values, Unicode, and later duplicate assignments retain literal meaning. Names beginning `C0_SESSION_ENV` are reserved for the private handoff and refuse before transport. Separate credential delivery leaves interactive stdin and TTY handling available to the guest. Management client keys and host trust state reside under host-only `auth/ssh-client`; `auth/ssh` remains the durable guest server/auth directory. Key preparation creates a fresh management client when needed, preserves the guest server key and unrelated authorization entries, and retains legacy management key material in a host-only archive rather than the guest mount. Legacy retirement removes only the matching identity and preserves unrelated authorization even when the guest public sidecar differs. Repeated preparation preserves active private keys, reconciles their public authorization and repairs management-key permissions before SSH attachment or retained-container start. Key generation and terminfo transfer retain their explicitly requested scope. SSH-agent forwarding grants signing capability to guest code and must be disableable when unused. Routine interactive terminfo transfer is per-user; explicit `cp-term` retains its system-wide behavior.

### Containment

Every process role must receive only the UID, capabilities, mounts, descriptors, network, and lifetime needed for its feature. Routine guest processes must remain under seccomp and no-new-privileges. Host namespace helpers require a separately documented, operation-specific privilege justification; helper authority must not flow to the runtime.

Host commands must consume protected orchestration inputs, validate actual resource identity and ownership before effects, pass user values literally, and refuse uncertain destructive actions. Cleanup must target positively attributed resources. Acquisition and publication must be separate trust stages, with input integrity established before consumption and published content immutable afterward.

Network listeners and host-service access must have an explicit feature purpose and scope; inbound exposure should use the narrowest supported address and agent access should be absent when unnecessary. A profile name is not evidence of fewer effective capabilities. Actual restrictions and service behavior require observations at their process and transport boundaries.

### Private Data

Credentials, private keys, tokens, and private user content must not enter logs, diagnostics, traces, command arguments recorded by process tooling, Git, image layers, build contexts, tools snapshots, or release bundles. Deliberate secret delivery uses the selected recipient and lifetime; public verifier keys are distinct nonsecret trust inputs. Auth mounts must expose only the material the feature requires, with the narrowest supported access mode.

Secret protection must cover success, failure, cancellation, native output, and helper paths. Ignore rules alone do not establish that tracked content or outgoing history is clean. Use synthetic values for verification; report a discovered real secret without reproducing it and require revocation/rotation and separately scoped removal before release.

### Release Security

Every release must be blocked while any known applicable unremediated CVE or other known security vulnerability is embedded in the project or delivered artifacts. This includes actively exploited vulnerabilities and all severities, direct and transitive dependencies, OS packages, base/runtime/helper images used by supported workflows, bundled interpreters, native binaries, assistant tools, installers, and compiled dependency copies. No available fix, a low severity, an unused default configuration, or an operational mitigation clears an applicable embedded vulnerability; remove the affected content or use an evidenced fixed build.

Before release, inventory exact source and artifact content, resolve all shipped component versions and identities, and assess current vendor/distribution advisories and known-exploitation data. Scan the final images and bundles as well as source/lockfiles; account explicitly for downloaded binaries, compiled static dependencies, and other content a selected scanner cannot identify. Bind evidence to the exact candidate, artifact digests, platforms, tool versions, advisory-data versions/times, results, and coverage. Changed candidate content invalidates affected evidence; release requires current advisory assessment of the unchanged final candidate.

Missing inventory, unsupported ecosystems, unreadable artifacts, failed scans, unavailable/stale advisory data, unresolved applicability, and unverified suppressions block release. A withdrawn advisory or a demonstrated non-applicable version/build finding can be closed with authoritative evidence for that exact artifact; this is not a waiver for an applicable vulnerability. Known-exploitation catalogs supplement full vulnerability sources and cannot replace them.

Release also requires secret checks of proposed tracked content, outgoing history, build contexts, and final artifacts, plus containment and data-preservation evidence. The release gate is a required decision supported by retained nonsecret evidence; no automated gate or clean security verdict is claimed by this documentation update. Unknown vulnerabilities cannot be ruled out by a clean known-vulnerability assessment.

## Validation

- Existing mount tests retain read-only host launcher/control surfaces, correct tools subpaths, ownership, and refused unsafe mappings.
- Existing tools tests retain the running guest on acceptance and the same container/root filesystem on restoration, including failure and shared-stage refusal.
- Existing cache and sharing tests retain manifest-sensitive identities, artifact validation, Docker-derived selection, and mode/workspace separation.
- Existing cleanup tests retain all container/image references and accepted or unknown content; failed discovery never becomes deletion authority.
- Credential regressions require value-free transport argv, unchanged host controls, literal guest environment and stdin/TTY/status behavior, private host client/trust storage, preserved server/unrelated authorization, and retained host-only legacy keys.
- Required security verification uses accepted/refused counterparts for extra capabilities, daemon/namespace exposure, symlink and alias redirection, unintended listeners, unsafe host cleanup, and secret-bearing output/persistence.
- Required release verification demonstrates that an applicable finding at any severity and an incomplete inventory/scan both block clearance for the exact candidate. Evidence of functionality alone does not satisfy this gate.

## Diagnostics

Build, lifecycle, overlay, transport, stage, and cleanup failures remain owned by their command and native boundary; callers must receive a failed result rather than fabricated success or absence. Security diagnostics must identify the nonsecret operation/resource and bounded cause without credential values or raw private payload. Release refusal must identify affected component/advisory or missing evidence and the action needed to clear it. Current native command-output handling is not a demonstrated universal sanitization mechanism.

## Boundaries

The owning host account and Docker operator can override controls and are outside guest containment. Declared writable host data and forwarded agent capabilities remain accessible to guest code. System-package changes in the disposable guest layer are not reproduced by tools publication. Whole-stage acceptance currently has no demonstrated secret-exclusion mechanism; it cannot by itself clear a release. This specification adds requirements, not new commands or permission to operate existing user runtimes.
