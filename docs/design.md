---
doc-graph: "When there is an intention to amend this document, first Adhere to [dc-doc-design]; otherwise, do not modify."
dg-limit: words<=15000
---

# c0dev Architecture Design

## Purpose

Explain how the host launcher, build pipeline, Docker guest, tools store, and workspace mounts realize the product model, while separating current mechanisms from security requirements without demonstrated enforcement.

## Orientation

This design serves maintainers of the current Bash launcher and Docker configuration. It preserves Docker-derived shared builds, workspace storage, protected host launcher inputs, and non-replacing tools operations. The [specification](spec.md) owns behavior and the release-security bar; implementation and a passing local test cannot weaken that bar. No optional-package subsystem or named-environment facade is part of this design.

## Terminology

| Term           | Meaning                                                                                 |
| -------------- | --------------------------------------------------------------------------------------- |
| Recipe         | Path-independent source identity of Dockerfiles and relevant copied inputs.             |
| Manifest       | Canonical resolved release selections used by one build.                                |
| Workspace      | Mode and real working folder sharing durable home storage.                              |
| Instance       | Workspace and build identifying a runtime container.                                    |
| Launcher upper | Persistent guest edits over the read-only host `bin/` lower, outside tools disposition. |

## Design Goals

Keep authority with the process that needs it, separate networked acquisition from publication, discover state from Docker, preserve deliberate durable data, and make immutable defaults distinguishable from native writable changes.

## Module Inventory

The product is one development-environment tool. These are engineering modules, not separately managed components.

| ID   | Module / realized surface                                                | Responsibility, inputs, and outputs                                                                    | Owned/reused seam                               | Decisions and gaps                                                      |
| ---- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------ | ----------------------------------------------- | ----------------------------------------------------------------------- |
| M-01 | Host router: `bin/c0`, `bin/c0-host-io`, `bin/c0-credentials`            | Host arguments, source root, mode, Docker facts → bounded build/lifecycle/attachment/tools actions     | SM-01 workspace ownership; SM-02 tools store    | D-04, D-09, D-10; complete secret-safe transport is unproved            |
| M-02 | Build and toolchain: Dockerfiles, `bin/c0-toolchain`, `bin/docker-hash`  | Recipe and upstream metadata → canonical manifest and validated shared images/payloads                 | SM-02 tools store                               | D-09; complete acquisition provenance and release scanning are unproved |
| M-03 | Guest and activation: Compose, entrypoint, `bin/activate`                | Selected image/mounts/manifest → dev execution and toolchain defaults                                  | SM-01 workspace ownership; SM-03 overlay policy | D-05, D-08, D-10; effective least privilege requires per-role evidence  |
| M-04 | Overlay handling: `docker/c0-overlay-check`, host helper functions       | Policy and exact namespace/volume → mounted lowers/uppers and complete stage report                    | SM-03 overlay policy                            | D-02, D-06, D-07; privileged helper minimization requires evidence      |
| M-05 | Tools store/publication: host tools functions, `docker/c0-publish-tools` | Verified build or captured stage → complete payload and published runtime reference; scoped restore/GC | SM-02 tools store                               | D-01, D-03, D-04; whole-stage secret exclusion is unproved              |

| ID    | Seam                            | Owner / direction     | Contract and test boundary                                                                                           |
| ----- | ------------------------------- | --------------------- | -------------------------------------------------------------------------------------------------------------------- |
| SM-01 | Docker workspace ownership      | M-01 → M-03/M-04      | Specification lifecycle/mount semantics; existing mount, storage, and sharing tests                                  |
| SM-02 | Immutable tools and publication | M-05 → M-01/M-02/M-03 | [Tools-store contract](tool-store-contract.md); tools-state, publication, cache, and retention tests                 |
| SM-03 | Home overlay policy             | M-04 → M-03/M-05      | Current `docker/home-overlays.conf` path-pair format; a separately governed formal overlay-policy contract is absent |

## Existing Surface Reuse Map

| ID    | Surface                                         | Required use / extension                                                | Preservation and limitation                                                      |
| ----- | ----------------------------------------------- | ----------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| RU-01 | Existing Bash launcher                          | Sequence host Docker actions through current ownership/mount validation | No alternate selector files or second lifecycle controller                       |
| RU-02 | Toolchain resolver and embedded manifests       | Resolve once for construction and select mounted defaults on activation | Do not resolve/download during login or status; not publisher-authenticity proof |
| RU-03 | Existing tools upper and launcher upper         | Preserve ordinary tool writes and separate guest launcher edits         | Tools restore cannot erase launcher or unrelated host data                       |
| RU-04 | Existing test fixtures and opt-in native suites | Observe stable command, mount, storage, and Docker boundaries           | Inert peers prove control flow; native tests prove only exercised integration    |

## Architecture

### Build Path

`bin/c0` constructs an owned temporary build context and concatenates base/tools or base/runtime fragments. `bin/c0-toolchain` resolves the supported releases once and emits canonical JSON plus build arguments. The tools identity binds the base/tools recipe and manifest; the runtime identity additionally binds runtime inputs. Equivalent mode/recipe/releases share completed artifacts across working folders. Python resolution intersects published final releases with the current official standalone build assets for standard CPython on Linux aarch64 GNU, retaining the 3.15 line and 3.15.2 security floor. The canonical manifest’s Python source binds the exact asset URL and SHA-256; the tools build constructs a private, scoped uv catalog for that asset and removes it after installation. This separates fixed-distribution availability from uv’s frozen internal catalog without falling back below the security floor.

The current tools builder installs non-system tools as `dev`, including managed Python/pip, Node/npm/pnpm through fnm, Semgrep, Rust/Cargo tools, and assistant installers. It retains explicit version and certificate-trust checks. Payload extraction includes `.cargo/bin`, `.rustup`, and complete `.local`. Cache acceptance compares completeness and embedded provenance; validated runtime images are published only after successful construction. Acquisition paths with executable upstream installers remain assurance limits, not verified routes merely because their final versions match.

Tools extraction creates a never-started container from the constructed image without store access or network, then copies its home data into private host staging. A fixed networkless publisher running the base image copies only the admitted tool roots into the unpublished candidate, preserves nested links without following them, records provenance, and writes completeness last. Constructed-image programs and startup hooks never execute with the tools volume writable. Source-container retirement requires the exact operation label and created state; fixed legacy container names supply no cleanup authority.

The private `docker/c0-security.py` construction helper backports the upstream destination-link guard to Debian’s system Python without replacing its interpreter. Base and runtime construction apply it after package installation, refuse unrecognized unprotected source, and retain before/after hashes. Tools and runtime recipe identities bind the helper bytes; a changed repair cannot reuse the previous default payload. The helper’s recorded patch provenance is not vulnerability clearance.

### Runtime Mount Path

Docker labels, actual container/image state, and mount inventories bind workspace and instance identity. Start reuses the matching instance or creates the published build against the workspace's positively identified durable storage. A different build cannot concurrently use the same writable home overlays. Ordinary stop removes workspace runtimes while retaining declared persistent data; restart composes stop and start.

Tools lower mounts expose only the selected payload. Tool upper/work storage lives in a Linux Docker volume; current macOS bind-backed upper semantics do not support the needed writes. A networkless host helper opens its own root and proc-directory descriptors before entering the exact runtime mount namespace, restores those held root/cwd bindings before executing programs, mounts configured paths, and exits. Programs and their loader stay in the protected helper filesystem; guest data is reached through the held proc directory. Overlay checks recognize the corresponding kernel option spelling and existing supported lower bindings. The runtime entrypoint waits for overlays before services.

The host `bin/` lower is read-only at `/run/c0/host-bin`; a separate guest launcher overlay exposes `/home/dev/bin`. Guest edits persist without writing host orchestration source. Git configuration, entrypoint, and overlay-control inputs are read-only. Declared configuration, caches, projects, and selected auth remain explicit host data surfaces, with confidentiality exposure distinct from write permission.

### Host Command Environment

M-01 owns one explicit projection of nonsecret launcher variables for every Compose call, including image construction and SSH-port discovery. The projection passes literal assignments to a child command without adding per-wrapper exports to the invoking shell. Optional Compose defaults remain in the YAML rather than being duplicated in Bash. Construction remains independent of runtime security selection.

Status uses that same projection for its shell-escaped launcher-input display, separately from observed container metadata. Its container tools selection cannot replace the launcher's tools value in that display. Per-session authentication files and unrelated host environment values never enter the projection; status remains metadata-only and performs no guest execution or image construction.

### Host Config And Log I/O

M-01 routes SSH preparation/configuration and Orca log reset, output, and startup watching through the fixed host I/O helper. It holds the selected checkout directory, opens descendant parents without following links, and validates held file identities, regular type, ownership, and single-link count before effects. Config updates replace a private staged file atomically; log reset truncates only a validated descriptor and log reads/watches retain that descriptor. Redirected, hardlinked, or non-regular control files refuse rather than becoming host read/write targets.

SSH preparation keeps management client keys and known-hosts state in host-only `auth/ssh-client`, apart from the guest-mounted `auth/ssh` server/auth directory. Missing pairs are generated in private temporary host storage and installed without overwriting active keys. Legacy management identity is derived from held private bytes; its matching authorization is replaced by the fresh client public key while unrelated entries and the server key remain. Original legacy files are retained in the private client archive and removed from the guest directory. Every host SSH prerequisite and retained-container start reconciles the selected client public identity from held private bytes, repairs its private-file mode, and restores missing matching authorization. Existing server configuration is retained on attachment; a missing configuration must be written successfully. Preparation never restarts a service or guest.

### Credential Attachments

The fixed host transport captures the executable, Docker/SSH connection arguments, selected guest, and host environment before parsing optional `auth/.env`. Parsed names and values remain data and never update host `os.environ` or Bash orchestration variables. Invalid literal lines generate value-free warnings; the private handoff namespace refuses as input.

M-01 encodes a versioned literal environment map into private environment fields, chunked below Docker's env-file line limit. Docker reads those fields from a private pipe descriptor through `--env-file`, leaving stdin separate. SSH receives only those private fields in its child environment and forwards their names with `SendEnv`; host control names from auth remain inside the encoded data. Client logging suppresses debug environment emission, and generated server configuration accepts the private handoff plus locale. Service health and stop probes carry no auth data; the actual service launch retains its credential environment.

Each attachment supplies the same fixed, nonsecret guest Python bootstrap. It validates and removes private fields, restores literal values in the guest environment, and executes the captured absolute program. Host and guest codec logic remain one private M-01 implementation; no public envelope-construction API or persisted guest secret file is introduced. The runtime explicitly supplies system Python for this handoff. The host controller passes through terminal descriptors, relays cancellation only to its captured child, and preserves guest/native statuses.

OpenSSH receives management identity and known-hosts paths through a temporary host-private directory alias to the validated client directory. This avoids OpenSSH's whitespace and token interpretation of arbitrary checkout paths without copying key bytes or changing persistent trust storage. The alias retires after the child exits. Host management authentication selects the host client identity and disables the host agent; the separate optional guest agent relay remains unchanged.

### Stage Inspection

The existing checker compares upper entries with the selected lower and exposes the complete configured tools stage. Tools display summarizes it without classifying payload versus state. Successful shell and SSH activation stays quiet. Launcher state is separate from tools inspection/disposition.

### Acceptance

M-01 validates the actual running container, mounts, payload, and runtime metadata. M-04 briefly pauses that container and streams merged tool archives through a networkless namespace helper into private host storage, then resumes it. The capture helper uses the same held helper-root/proc bindings as mounting, so the archive program and its loader come from the protected helper image rather than the mutable guest filesystem. M-05 validates archive paths, copies the complete parent into an unpublished candidate, applies the archives, records identity/provenance, writes completeness last, and publishes a derived shared runtime image.

The existing guest continues on its fixed tools mount and writable stage. Publication changes the Docker reference used by later creation; it does not replace the guest filesystem or clear the upper. Namespace capture and networkless publication have separate authority and do not execute staged payload as publisher code.

### Restoration

M-01 initializes restore selection from the actual guest mount and compares the Docker-published selection only when initial recipe-image inspection succeeds; an absent image or failed initial inspection skips that comparison. It separately verifies that no other container references the guest's home storage. It stops the exact guest, rechecks exclusivity, and invokes a fixed helper clearing only configured tools upper/work paths. It restarts and validates that same guest even when clearing failed, preserving container-layer and launcher data. A resolved selection mismatch or shared stage refuses rather than migrating the guest. The skipped publication comparison is a current realization gap against the specification's hardened fail-closed requirement.

### Selection And Collection

New creation resolves a validated Docker-published runtime reference; existing actions use actual inspected mounts and metadata. No checkout pin or saved volume mapping is created. Collection protects tools referenced by every running/stopped/recovery container and published runtime image, then limits deletion to positively identified unreferenced rebuildable caches. Accepted and unknown legacy data remain retained. Required discovery failure blocks deletion.

## Design Decisions

| ID   | Decision                                                      | Rationale                                                                    | Alternatives                                                                                       | Affected surfaces | Status  |
| ---- | ------------------------------------------------------------- | ---------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- | ----------------- | ------- |
| D-01 | Tools commands manage stage disposition                       | Keeps construction separate and reviewable                                   | Running installers during stage management duplicates construction                                 | M-01/M-05         | current |
| D-02 | Complete configured tools upper defines the stage             | Arbitrary native state cannot be classified reliably by path                 | Per-tool allowlists hide new support/state files                                                   | M-04/M-05         | current |
| D-03 | Acceptance creates immutable child content                    | Retains stable parent content without guest store authority                  | In-place mutation mixes published states                                                           | M-05/SM-02        | current |
| D-04 | Preserve fixed guest mounts during tools operations           | Protects guest filesystem and process identity                               | Replacement during tools disposition discards unrelated guest state; live lower swapping is unsafe | M-01/M-05         | current |
| D-05 | Mount only the selected tools subpath                         | Limits cross-payload browsing and metadata exposure                          | Whole-volume read access exposes other workspace state                                             | M-03/SM-02        | current |
| D-06 | Keep overlay upper/work in Linux workspace storage            | Supplies required OverlayFS semantics and durability                         | Current macOS host-backed upper fails merged writes                                                | M-04              | current |
| D-07 | Redirect XDG data/state to declared host storage              | Makes common mutable data durable and visible                                | Whole-stage persistence alone hides ordinary host-managed state                                    | M-03              | current |
| D-08 | Keep successful attachment quiet                              | Avoids reporting a stage on every shell entry                                | Repeated overlay summaries obscure native shell output                                             | M-01/M-03         | current |
| D-09 | Publish recipe/manifest-bound shared builds through Docker    | Joins release identity, discovery, sharing, and native references            | Recipe-only identity reuses stale releases; saved checkout selectors drift from Docker             | M-01/M-02/M-05    | current |
| D-10 | Separate host launchers from guest launcher writes            | Keeps future host execution outside guest write authority                    | Direct writable host `bin/` creates delayed host execution                                         | M-01/M-03/M-04    | current |
| D-11 | Keep credential values in a private guest-environment handoff | Preserves literal guest values without mixing host controls or exposing argv | Raw environment arguments disclose values; exporting arbitrary auth names changes host execution   | M-01/M-03         | current |

## Component Responsibilities

The host router owns sequencing and resource attribution. Build code owns acquisition and candidate construction. Guest execution owns deliberate native work within declared mounts. Overlay helpers own only the exact namespace/mount operation. Tools publication owns unpublished immutable content and Docker reference publication; it does not interpret arbitrary guest instructions as host code. No package installer or separate local-service container is introduced.

## API Shape

[Specification public surfaces](spec.md#public-surface) own exposed behavior; the tools contract owns storage and transaction shape. `docker/home-overlays.conf` supplies the current internal path-pair policy. Internal function names and fixture implementations are not additional public APIs.

## Workflow And Data Flow

Build arguments and one resolved manifest flow through M-02 to complete tools/runtime artifacts and Docker publication. Start flows from inspected Docker state through M-01 ownership and M-04 mounts to M-03 services. Guest writes flow to declared host data or workspace uppers. Explicit acceptance flows through paused capture and isolated publication to a new shared reference while leaving the guest intact. Restore flows through exclusive storage proof, bounded clear, and same-container restart. Cleanup consumes complete resource references before any candidate deletion.

## Policy And Authority Boundaries

Goals fix outcomes, specification fixes behavior, contract fixes the tools seam, and this design fixes mechanisms. The security reference explains current controls and missing assurance. A successful source check or image build establishes neither least privilege nor release-security clearance.

## Upstreamable Surface

Recipe/manifest-bound artifact identity, Docker-derived resource discovery, immutable publication, complete stage reporting, and reference-aware cleanup are general mechanisms. OrbStack agent relay and macOS bind limitations are platform-specific integration.

## Private Implementation Surface

Temporary context names, helper image selection, archive transport, fixed shell bodies, and function decomposition may change while preserving behavior, provenance, authority, and failure contracts. New helper authority requires evidence of necessity; a convenience refactor does not supply it.

## Constraints References

[Constraints](constraints.md#constraints) carry forbidden authority, host-exposure, release, secret, and cleanup patterns. They apply to all modules; a local helper must not become a weaker second owner.

## Preservation Requirements

- Preserve declared host configuration/data, guest launcher state, unrelated files, and supported storage lineage.
- Preserve the running guest during tools acceptance and the same guest filesystem during restoration, including failed clears.
- Preserve immutable referenced payloads and conservatively retain unknown storage.
- Preserve recipe/manifest-sensitive identity, current version/security floors, and mounted-default selection.
- Preserve actual capability/seccomp/NNP controls and explicit guest administration while reducing unnecessary authority through evidenced changes.

## Failure Modes

Required Docker ownership, mount, lineage, and reference validations refuse dependent mutation when their evidence is unavailable or conflicting. Restore's initial recipe-image probe currently skips publication comparison on inspection failure, so it does not realize the hardened fail-closed requirement for that observation. Build failure retains published artifacts. Snapshot failure attempts same-container resume and removes owned host temporaries. Publication may leave an unselected complete candidate but does not clear the live stage. Failed restore attempts same-container restart and remains failed. Neither failure nor a clean stage supplies permission to remove host mounts or unknown resources.

Current gaps in complete input verification, secret exclusion, vulnerability coverage, and helper minimization remain requirements at the [specification](spec.md#release-security); this design selects no unimplemented scanner, broker, syscall sandbox, or replacement installer.

## Acceptance Criteria

- Existing command and mount tests preserve protected host lowers, literal inputs, owned-resource validation, and refused unsafe mappings.
- Tools-state and native publication tests preserve guest identity and filesystem through acceptance/restore and their failure paths.
- Build/cache and sharing tests distinguish changed manifests, source recipes, modes, working folders, and referenced artifacts.
- Cleanup tests retain stopped/image references, accepted data, and unknown lineage.
- Security acceptance additionally requires the specification's intended containment, secret, input-verification, and release evidence; source configuration alone does not establish those effects.
