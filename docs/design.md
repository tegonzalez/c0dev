---
doc-graph: "When there is an intention to amend this document, first Adhere to [dc-doc-design]; otherwise, do not modify."
dg-limit: words<=15000
---

# c0dev Architecture Design

## Purpose

Explain how the host launcher, build pipeline, Docker guest, tools store, and workspace mounts realize the product model. Locked acquisition describes the intended construction architecture; the current launcher and Dockerfiles do not yet implement it. Runtime and storage mechanisms remain current source observations.

## Orientation

This design serves maintainers of the current Bash launcher and Docker configuration. It preserves Docker-derived shared builds, workspace storage, protected host launcher inputs, and non-replacing tools operations. The [specification](spec.md) owns behavior and the release-security bar; implementation and a passing local test cannot weaken that bar. No optional-package subsystem or named-environment facade is part of this design.

## Terminology

| Term           | Meaning                                                                                                              |
| -------------- | -------------------------------------------------------------------------------------------------------------------- |
| Recipe         | Path-independent source identity of Dockerfiles and relevant copied inputs.                                          |
| Manifest       | Canonical toolchain selections embedded in one payload, including retained schema-1 metadata.                        |
| Signature file | `docker/signatures.json`: the single construction-input authority binding exact content and its verification method. |
| Workspace      | Mode and real working folder sharing durable home storage.                                                           |
| Instance       | Workspace and build identifying a runtime container.                                                                 |
| Launcher upper | Persistent guest edits over the read-only host `bin/` lower, outside tools disposition.                              |

## Design Goals

Keep authority with the process that needs it, separate networked acquisition from publication, discover state from Docker, preserve deliberate durable data, and make immutable defaults distinguishable from native writable changes.

## Module Inventory

The product is one development-environment tool. These are engineering modules, not separately managed components.

| ID   | Module / realized surface                                                              | Responsibility, inputs, and outputs                                                                                    | Owned/reused seam                               | Decisions and gaps                                                                      |
| ---- | -------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- | --------------------------------------------------------------------------------------- |
| M-01 | Host router: `bin/c0`, `bin/c0-host-io`, `bin/c0-credentials`                          | Host arguments, source root, mode, Docker facts → bounded build/lifecycle/attachment/tools actions                     | SM-01 workspace ownership; SM-02 tools store    | D-04, D-09, D-10; complete secret-safe transport is unproved                            |
| M-02 | Build and toolchain: Dockerfiles, tracked signature loader/verifier, `bin/docker-hash` | Recipe and signature file → verified inputs, embedded manifest, shared images/payloads; intended construction baseline | SM-02 tools store                               | D-09, D-12; signature-file consumption and pre-use verification are not yet realized    |
| M-03 | Guest and activation: Compose, entrypoint, `bin/activate`                              | Selected image/mounts/manifest → dev execution and toolchain defaults                                                  | SM-01 workspace ownership; SM-03 overlay policy | D-05, D-08, D-10; effective least privilege requires per-role evidence                  |
| M-04 | Overlay handling: `docker/c0-overlay-check`, host helper functions                     | Policy and exact namespace/volume → mounted lowers/uppers and complete stage report                                    | SM-03 overlay policy                            | D-02, D-06, D-07; privileged helper minimization requires evidence                      |
| M-05 | Tools store/publication: host tools functions, `docker/c0-publish-tools`               | Verified build or captured stage → complete payload and published runtime reference; scoped restore/GC                 | SM-02 tools store                               | D-01, D-03, D-04; whole-stage secret exclusion is unproved                              |

| ID    | Seam                            | Owner / direction     | Contract and test boundary                                                                                           |
| ----- | ------------------------------- | --------------------- | -------------------------------------------------------------------------------------------------------------------- |
| SM-01 | Docker workspace ownership      | M-01 → M-03/M-04      | Specification lifecycle/mount semantics; existing mount, storage, and sharing tests                                  |
| SM-02 | Immutable tools and publication | M-05 → M-01/M-02/M-03 | [Tools-store contract](tool-store-contract.md); tools-state, publication, cache, and retention tests                 |
| SM-03 | Home overlay policy             | M-04 → M-03/M-05      | Current `docker/home-overlays.conf` path-pair format; a separately governed formal overlay-policy contract is absent |

## Existing Surface Reuse Map

| ID    | Surface                                         | Required use / extension                                                                 | Preservation and limitation                                                                                                         |
| ----- | ----------------------------------------------- | ---------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| RU-01 | Existing Bash launcher                          | Sequence host Docker actions through current ownership/mount validation                  | No alternate selector files or second lifecycle controller                                                                          |
| RU-02 | Embedded manifests and offline validation       | Derive new manifests from the signature file; validate retained metadata without network | Existing schema-1 metadata preserves identity and activation semantics; recognition alone does not verify acquired input signatures |
| RU-03 | Existing tools upper and launcher upper         | Preserve ordinary tool writes and separate guest launcher edits                          | Tools restore cannot erase launcher or unrelated host data                                                                          |
| RU-04 | Existing test fixtures and opt-in native suites | Observe stable command, mount, storage, and Docker boundaries                            | Inert peers prove control flow; native tests prove only exercised integration                                                       |

## Architecture

### Build Path

`bin/c0` constructs an owned temporary build context and concatenates base/tools or base/runtime fragments. In the intended construction baseline, a tracked offline loader validates [the signature file](../docker/signatures.json), derives canonical toolchain metadata and exact build arguments, and supplies the same recorded inputs to tools and runtime construction. Dockerfiles and acquisition scripts consume the validated signature data copied into the build context; the payload retains that same source data at `/home/dev/.local/share/c0/signatures.json`. The tools and runtime identities bind the complete signature file, its SHA-256-bound native inputs, their recipes, and verification-relevant copied inputs; runtime identity also binds the tools identity so it cannot reuse a publication naming an older payload after a tools change. Equivalent inputs share completed artifacts across working folders. The signature file does not select the active runtime or replace Docker's publication and mount discovery.

The current implementation instead invokes `bin/c0-toolchain` to discover releases and also uses its offline validation mode for retained manifests. That discovery executable leaves version control while its local bytes remain preserved. Tracked code retains the offline validation behavior; no build, validation, stage, activation, or cache path invokes the local discovery executable or copies it into a build context. New lock-bound identities use a distinct domain from legacy manifest-only identities, whose exact representation remains at the [tools-store contract](tool-store-contract.md#identity).

The tools builder retains unprivileged user-tool installation, managed Python/pip, Node/npm/pnpm with fnm's native layout, Semgrep, Rust/Cargo tools, and every assistant CLI. Payload extraction includes `.cargo/bin`, `.rustup`, and complete `.local`. Cache acceptance compares completeness and embedded provenance; validated runtime images are published only after successful construction. Version and certificate checks establish bounded behavior after the relevant input signatures have been verified; they cannot select replacement inputs or substitute for pre-use signature verification.

Tools extraction creates a never-started container from the constructed image without store access or network, then copies its home data into private host staging. A fixed networkless publisher running the base image copies only the admitted tool roots into the unpublished candidate, preserves nested links without following them, records provenance, and writes completeness last. Constructed-image programs and startup hooks never execute with the tools volume writable. Source-container retirement requires the exact operation label and created state; fixed legacy container names supply no cleanup authority.

The private `docker/c0-security.py` construction helper backports the upstream destination-link guard to Debian’s system Python without replacing its interpreter. Base and runtime construction apply it after package installation, refuse unrecognized unprotected source, and record before/after SHA-256 values. Tools and runtime recipe identities bind the helper bytes; a changed repair cannot reuse the previous default payload. The helper’s recorded patch provenance is not vulnerability clearance. The guest credential bootstrap in `bin/c0-credentials` and toolchain selector in `bin/activate` invoke `/usr/bin/python3`; those consumers and system-package dependencies must be accounted for before interpreter provisioning changes.

### Locked Acquisition

The construction trust roots are the reviewed repository's Dockerfiles and [single signature file](../docker/signatures.json), together with the installed Docker software. An image fetched at the recorded OCI digest is trusted as a complete image. Tools, public keyrings, libraries and other files already contained in that image inherit its trust. A verified package or release archive similarly carries trust for its complete contents, including bundled runtimes, vendored code and scripts. Construction does not recursively seek new publisher proofs for those contained files.

A signature record fixes the accepted content and the method used to verify it. A stored SHA-256 signature is verified by comparing the acquired file's SHA-256 digest with the trusted recorded value. An OpenPGP signature is verified under the recorded trusted signing key. These methods establish the project's accepted content binding through different cryptographic operations; a locally computed SHA-256 value alone does not identify its publisher. Direct-download signature preparation first compares the artifact with the publisher's SHA-256 value, then retains that established value for later construction.

A new acquisition occurs when bytes are fetched from outside an already verified image, package or archive. Dependency downloads performed by a trusted native package manager follow that manager's verification chain. A script's separate curl/wget download needs its own recorded verification route before its result is extracted, installed or executed. Trust-chain verification, frozen selection and installation/refusal QA are separate results: a package can have a valid publisher binding while its selection remains floating, and a recorded selection does not prove that current code enforces its signature.

#### Signature File

`docker/signatures.json` is the sole source-managed authority for construction input identities and verification routes. It is read as data, never sourced as shell. The loader rejects duplicate keys or identities, unknown schemas, missing required records, unresolved references and platform mismatches. An incomplete input record is not a usable signature. Dockerfiles, `c0 build` and acquisition scripts obtain their expected values from the same validated file; embedded metadata and generated build arguments are projections, not alternate authorities.

Native lockfiles remain in their native formats so trusted package managers can verify their own downloads. The signature file binds each consumed native input by path and SHA-256 digest before the manager reads it. A native format's existing SHA-512 integrity values remain usable where its package manager requires them; construction introduces no parallel SHA-512 inventory. SHA-256 is the project's stored digest for independently acquired files and subordinate input files.

| Record               | Content and use                                                                                                                                            |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Image                | Registry/repository, platform and OCI manifest digest used by Docker before image use.                                                                     |
| Release artifact     | Exact publisher URL, version/platform/filename and publisher-established SHA-256 value checked before extraction, installation or execution.               |
| Native package input | Trusted manager and installation parent, repository/registry scope, SHA-256-bound native lock or frozen package set, and enabled native verification mode. |
| Imported file        | Exact local keyring or transformation file and SHA-256 binding; a transformation also binds its known input and expected output.                           |
| Git source           | Trusted author/repository, full immutable commit ID and consumed tree/path; retrieved file bindings support later offline SHA-256 comparison.              |
| Missing signature    | Named input and missing evidence; no observed local digest is substituted for a trusted expected value.                                                    |

All tools named by the current recipes remain required. The signature-file architecture is the intended construction mechanism; the current launcher and Dockerfiles do not yet enforce it. The signature file is input data, not an installation-audit report. Construction has no dependency on local research inventories, candidate manifests or approval-history files.

#### OCI Images

During signature preparation, obtain the target platform's manifest digest from the repository named by the checked-in Dockerfile, using the trusted Docker client/registry. Record the repository, `linux/arm64` platform and `sha256:` manifest digest. Record a multi-platform index digest distinctly when one is used. A local image configuration ID and the SHA-256 digest of a `docker save` archive are different identities from the registry manifest digest.

During construction, pull `repository@sha256:<recorded-manifest-digest>` with the recorded platform and use that same digest-qualified reference in `FROM` and execution-helper invocations. Docker verifies the image content. Before use, compare the image's `RepoDigests` and platform with the signature record; mismatch or failed Docker verification refuses the dependent operation. Bun base images and Alpine helpers follow this procedure. Their contained tools and keyrings need no second file-signature inventory. [Docker's digest-pull procedure](https://docs.docker.com/reference/cli/docker/image/pull/) defines the digest-qualified reference.

#### APT Packages

The verified image supplies trusted APT software and Debian archive signing keys. A separately imported vendor key is trusted only for its recorded repository through `signed-by`. APT verifies this chain before installation:

1. The trusted archive key verifies the OpenPGP signature on `InRelease`, or on `Release` through `Release.gpg`.
1. The signed release metadata binds the selected package index through its SHA-256 digest.
1. That index binds each acquired `.deb` through its SHA-256 digest.
1. APT compares the acquired bytes with those secure digests and refuses signature or digest failures before package installation.

This chain establishes trust in the selected packages and their complete contents, including maintainer scripts. Repository signatures bind the release metadata; APT does not require an additional publisher signature on each delivered `.deb`. There is no custom signature check for every file inside a package. TLS certificate verification protects an HTTPS connection; the archive signing key and signed metadata establish the package signing chain. [APT's archive-chain description](https://manpages.debian.org/trixie/apt/apt-secure.8.en.html) defines these native operations.

Use only the repository/snapshot configuration and frozen package selections named by the signature file, including the full dependency package set or immutable repository state needed to reproduce selection. Run `apt-get update` with signature and secure-digest verification enabled, then install the recorded `package=version` selections. Signed current metadata alone does not freeze selection. A valid signing chain with floating versions is a selection failure, not a missing package-signing proof. Do not pass `--allow-unauthenticated` or use `trusted=yes`; these are literal native bypass names. Unavailable historical metadata must not cause an implicit repository, snapshot or validation-policy change.

The vendor-key records bind the exact file, primary fingerprint, publisher URL and repository scope. The 1Password key in `docker/1password.asc` has primary fingerprint `3FEF9748469ADBE15DA7CA80AC2D62742012EA22`; `docker/cloud.google.gpg` has primary fingerprint `35BAA0B33E9EB396F59CA838C0BA5CE6DC6315A3`. Before enabling either repository, compare the local key file's SHA-256 digest with its signature record and enforce its `signed-by` scope. The [1Password instructions](https://developer.1password.com/docs/cli/get-started/) and [Google instructions](https://cloud.google.com/sdk/docs/install) identify their publisher key locations and scoped configuration. The existing Google source is a metadata repository; it does not add a Google SDK installation.

#### Release Archives And Direct Binaries

Signature preparation downloads the exact platform artifact as inert data, obtains its SHA-256 value from the named publisher's digest file, release asset record or versioned manifest, computes SHA-256 over the downloaded bytes, and requires equality before recording that value. The trusted publisher/release supplies the expected digest. This route does not require a second oracle, attestation service or separate signing-key ceremony.

Ordinary construction downloads only the recorded URL to private staging and compares its SHA-256 digest with the signature-file value before extraction, installation or execution. For a validated signature record, the following illustrative boundary uses `recorded_url` and `recorded_sha256` supplied by the tracked loader; the trusted Linux image supplies curl and sha256sum:

```sh
set -eu
staging="$(mktemp -d)"
curl --fail --location --proto '=https' --output "$staging/artifact" "$recorded_url"
printf '%s  %s\n' "$recorded_sha256" "$staging/artifact" | sha256sum --check --strict -
```

A matching digest makes that staged file eligible for the subsequent installer/extractor. A mismatch returns failure and never invokes it. The caller owns staging cleanup and preserves unrelated files on failure. Reusing a downloaded archive compares its envelope's SHA-256 digest again; its contained files inherit trust.

| Download         | Publisher binding and construction use                                                                                                                                                                                                                                                                                                                                                                                                                         |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| uv               | The publisher's versioned release supplies `uv-aarch64-unknown-linux-gnu.tar.gz.sha256` or the matching `sha256.sum` entry. Compare the archive itself with that SHA-256 value before extraction; the digest-file asset's own digest does not identify the archive.                                                                                                                                                                                            |
| Managed Python   | The [standalone publisher](https://github.com/astral-sh/python-build-standalone/releases) supplies `SHA256SUMS`. Bind the Python version, standalone build, platform, archive URL and its SHA-256 entry. Supply these signature-file values through uv's [local catalog override](https://docs.astral.sh/uv/reference/environment/#uv_python_downloads_json_url); verify before extraction. Bundled pip/ensurepip content inherits the Python archive's trust. |
| fnm              | The [fnm release asset record](https://github.com/Schniz/fnm/releases) supplies SHA-256 for the platform ZIP. Compare the downloaded ZIP before unzip; the record establishes the expected value without another sidecar.                                                                                                                                                                                                                                      |
| Node             | The selected Node release's `SHASUMS256.txt` supplies the platform archive SHA-256 value. The [inspected fnm downloader](https://raw.githubusercontent.com/Schniz/fnm/v1.39.0/src/downloader.rs) extracts without a SHA-256 comparison; use the signature-file archive route before placing Node in fnm's existing layout. Preserve fnm default/use and package-manager entrypoints. Bundled npm inherits the archive's trust.                                 |
| Rustup bootstrap | The [rustup publisher route](https://rust-lang.github.io/rustup/installation/other.html) supplies versioned `rustup-init` and `.sha256` sidecar. Compare the binary with the recorded SHA-256 value before execution rather than executing a moving shell bootstrap.                                                                                                                                                                                           |
| Orca             | The [Orca release asset record](https://github.com/stablyai/orca/releases) supplies the arm64 `.deb` SHA-256 value. Compare before passing the direct package to APT. Newly fetched dependencies follow the APT signing chain; contained Electron files inherit package trust.                                                                                                                                                                                 |
| Go distribution  | The [Go download metadata](https://go.dev/dl/?mode=json) supplies platform filenames and SHA-256 values. An admitted Go installation follows this archive route. Current tracked recipes do not install Go.                                                                                                                                                                                                                                                    |

#### Native Ecosystem Packages

A manager supplied by a trusted image, package or archive is trusted to verify its supported package acquisitions. Construction validates the signature file, compares the SHA-256 digest of each native input before the manager reads it, then uses that native lock and its enabled verification mode. `managed_python`, `requirements_file`, `recorded_version` and `crate` below are data from the validated signature file and installation context. Exact native input paths and digests belong to the signature file rather than a second inventory.

| Family                                                      | Verification procedure                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Python: pip, Semgrep and dependencies                       | Use exact requirements with `--hash=sha256:` entries and trusted `uv pip sync --python "$managed_python" --require-hashes "$requirements_file"`, or an equivalent frozen uv input with enforced artifact hashes. Newly fetched source-build requirements need their own pinned hash-checked native input. Preinstall those requirements through the same route before disabling build isolation when that mode is selected. [uv's hash setting](https://docs.astral.sh/uv/reference/settings/#require-hashes) and [pip's secure-install procedure](https://pip.pypa.io/en/stable/topics/secure-installs/) own the native operations. |
| npm and pnpm                                                | Use the SHA-256-bound exact manifest and native lock in a dedicated context, then `npm ci --no-audit --no-fund` or `pnpm install --frozen-lockfile`. Retain native integrity fields, including SHA-512 values already required by the ecosystem. Preserve the fnm prefix, package trees and declared CLI bins when placing the result; npm ci is a project operation, not a global-install flag. [npm's native lock](https://docs.npmjs.com/cli/v11/configuring-npm/package-lock-json/) and [ci procedure](https://docs.npmjs.com/cli/v11/commands/npm-ci/) define these inputs.                                                     |
| Bun assistant packages                                      | Use the SHA-256-bound exact manifest and `bun.lock` with `bun install --frozen-lockfile` and native integrity verification enabled. Preserve global command availability for every assistant CLI. Never pass `--no-verify`, the native integrity bypass. [Bun's lockfile](https://bun.sh/docs/pm/lockfile) and [integrity mode](https://bun.sh/docs/pm/cli/install#integrity-checking) define this route.                                                                                                                                                                                                                            |
| Cargo tools: fd, ripgrep, ast-grep, Zellij, Nu, cargo-cache | Pin the root crate version and consume the SHA-256-bound complete `Cargo.lock` in its verified source/package context. A retained packaged lock uses `cargo install --locked --version "=$recorded_version" "$crate"`; a prepared verified source context uses `cargo install --locked --path <verified-source>`. Cargo compares registry downloads with native SHA-256 values. A missing usable lock refuses construction instead of resolving a new dependency set. [Cargo install](https://doc.rust-lang.org/cargo/commands/cargo-install.html#dealing-with-the-lockfile) distinguishes the root version and dependency lock.     |
| Rust components and wasm target                             | Execute the verified rustup bootstrap against the exact numbered/dated toolchain, component set and publisher channel manifest named by the signature file. A fixed local distribution cache supplies the SHA-256-verified manifest through `RUSTUP_DIST_SERVER`; Rustup compares component archives with the manifest's secure digests. Never select a moving default channel. The [Rustup distribution override](https://rust-lang.github.io/rustup/environment-variables.html) supplies the native route; selected-version integration with the local cache remains an implementation requirement.                                |
| Go modules                                                  | For an admitted Go build, bind `go.mod` and `go.sum` through the signature file and use trusted Go with its public module database `sum.golang.org` enabled and `go build -mod=readonly`. Go verifies native module SHA-256 bindings before use. `go mod verify` checks cached-content changes rather than replacing acquisition verification. [Go's module verification](https://go.dev/ref/mod#authenticating) owns this route. A private-module authority needs its own bounded verification strategy. Current tracked recipes do not add Go.                                                                                     |

Files already contained in a native-verified package, including scripts and optional platform binaries, need no additional publisher proof. A hook or build script that independently fetches another artifact creates a new acquisition boundary. Fetch that artifact through the recorded native or SHA-256 route before use; the enclosing script's signature does not verify new remote bytes. Hooks can execute without network access after all inputs are acquired, while ordinary supported native-manager downloads retain their native verification chain.

The exact opencode install hook can fall back to a fresh npm platform-package install outside its Bun lock. Construction must pre-acquire the platform package through the recorded frozen native set and refuse that fallback download, or provide an equivalent signature-bound native acquisition. Claude and pnpm hooks use contained optional platform packages without a download fallback. bcrypt supplies Linux arm64 native prebuilds; a failed prebuild test or forced source build can invoke node-gyp. That source-build route needs recorded, verified header/build inputs before use; do not infer their verification from the contained prebuild. Signature-file presence and script-disabled native dry runs do not establish installation/refusal QA for these paths.

#### Vendor Installer Payloads

An installer downloaded for execution must have its signature checked before execution, and each new external payload it fetches must follow its own recorded verification route. Prefer direct signature-verified payload installation that preserves the tool's native files and entrypoints. When retaining an installer, bind the installer and downstream acquisitions to the single signature file. A `curl | sh` or `curl | bash` pipeline cannot perform the required pre-execution SHA-256 comparison of the complete acquired script.

| Tool   | Publisher binding and required use                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Droid  | The [Factory installer](https://app.factory.ai/cli) identifies versioned `https://downloads.factory.ai/factory-cli/releases/<version>/linux/arm64/droid` and its `.sha256` sidecar. Establish the expected binary SHA-256 during signature preparation, then compare against that stored value before installation/execution. The unchecked moving installer must not execute first.                                                                                         |
| Devin  | The [publisher installer](https://cli.devin.ai/install.sh) identifies the versioned manifest's `platforms["aarch64-unknown-linux"].url` and `.sha256` fields. Record the selected bundle URL and SHA-256, then verify before tar extraction. Ordinary builds never resolve `current/manifest.json`; an unchecked or locally transformed installer cannot precede verification. A contained setup program inherits bundle trust; a new setup download requires its own route. |
| Cursor | The [publisher installer](https://cursor.com/install) names a versioned CLI archive but supplies no established expected SHA-256 in the inspected route. A local observed digest is not an accepted signature. Establish publisher SHA-256 evidence or a separately bounded human verification strategy before treating that acquired payload as verified. Preserve the existing Cursor capability while the missing signature affects new candidate construction.           |

#### Git And Other Imported Inputs

For a trusted author/repository, record the full immutable commit ID in the signature file, fetch that object using trusted Git over the named authority's secure transport, compare `git rev-parse --verify 'FETCH_HEAD^{commit}'` with the recorded ID, and check out that exact commit detached. Do not resolve a moving tag during construction. This route retains the established Git commit-ID mechanism; it does not introduce a weak file-digest verification alternative. [Git fetch](https://git-scm.com/docs/git-fetch) and [revision verification](https://git-scm.com/docs/git-rev-parse) define the native operations. Separately acquired submodule or Git LFS content needs its own recorded identity and applicable verification route.

The Moby seccomp route binds its trusted author/GitHub source at commit `836ae4d37ef2ec995c77c99fc55f5b5f3af3a897`, path `seccomp/default.json`, and SHA-256 in the signature file. Retrieve the file at that commit, compare the selected bytes, then retain the SHA-256 binding for offline use. Explicit profile replacement remains available; ordinary builds/start perform no update discovery. This named-author route does not authorize arbitrary repositories solely because GitHub hosts them.

A standalone keyring, externally imported patch or other source outside the named trust routes needs an exact source/content binding and bounded human verification strategy before use. For a transformation, the signature file binds the upstream package/module input, helper file and expected output by SHA-256; refuse an unknown input or output mismatch. Project-owned orchestration source remains governed by repository review rather than recursive self-signing. The system-Python transformation preserves Debian's interpreter and uses this exact input/helper/output boundary; its signature records do not themselves prove the current helper enforces those comparisons.

Missing evidence names the newly acquired input and refuses its dependent candidate use while preserving existing published tools and unrelated verified inputs. No live release resolver, advisory feed or suitability assessment enters ordinary construction. Those processes stay outside the repository; only reviewed signature-file and bound native-input changes alter future acquisition.

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

| ID   | Decision                                                                                        | Rationale                                                                                                                                | Alternatives                                                                                                                                                       | Affected surfaces | Status  |
| ---- | ----------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------- | ------- |
| D-01 | Tools commands manage stage disposition                                                         | Keeps construction separate and reviewable                                                                                               | Running installers during stage management duplicates construction                                                                                                 | M-01/M-05         | current |
| D-02 | Complete configured tools upper defines the stage                                               | Arbitrary native state cannot be classified reliably by path                                                                             | Per-tool allowlists hide new support/state files                                                                                                                   | M-04/M-05         | current |
| D-03 | Acceptance creates immutable child content                                                      | Retains stable parent content without guest store authority                                                                              | In-place mutation mixes published states                                                                                                                           | M-05/SM-02        | current |
| D-04 | Preserve fixed guest mounts during tools operations                                             | Protects guest filesystem and process identity                                                                                           | Replacement during tools disposition discards unrelated guest state; live lower swapping is unsafe                                                                 | M-01/M-05         | current |
| D-05 | Mount only the selected tools subpath                                                           | Limits cross-payload browsing and metadata exposure                                                                                      | Whole-volume read access exposes other workspace state                                                                                                             | M-03/SM-02        | current |
| D-06 | Keep overlay upper/work in Linux workspace storage                                              | Supplies required OverlayFS semantics and durability                                                                                     | Current macOS host-backed upper fails merged writes                                                                                                                | M-04              | current |
| D-07 | Redirect XDG data/state to declared host storage                                                | Makes common mutable data durable and visible                                                                                            | Whole-stage persistence alone hides ordinary host-managed state                                                                                                    | M-03              | current |
| D-08 | Keep successful attachment quiet                                                                | Avoids reporting a stage on every shell entry                                                                                            | Repeated overlay summaries obscure native shell output                                                                                                             | M-01/M-03         | current |
| D-09 | Publish recipe/manifest-bound shared builds through Docker                                      | Joins release identity, discovery, sharing, and native references                                                                        | Recipe-only identity reuses stale releases; saved checkout selectors drift from Docker                                                                             | M-01/M-02/M-05    | current |
| D-10 | Separate host launchers from guest launcher writes                                              | Keeps future host execution outside guest write authority                                                                                | Direct writable host `bin/` creates delayed host execution                                                                                                         | M-01/M-03/M-04    | current |
| D-11 | Keep credential values in a private guest-environment handoff                                   | Preserves literal guest values without mixing host controls or exposing argv                                                             | Raw environment arguments disclose values; exporting arbitrary auth names changes host execution                                                                   | M-01/M-03         | current |
| D-12 | Consume one signature file through tracked offline loading and verified local installation      | Makes input selection reviewable and prevents installer/dependency downloads from bypassing verification; intended construction baseline | Build-time discovery changes inputs without review; pinning installer scripts alone leaves downstream downloads floating; removing tools loses required capability | M-01/M-02         | current |

## Component Responsibilities

The host router owns sequencing and resource attribution. Build code owns acquisition and candidate construction. Guest execution owns deliberate native work within declared mounts. Overlay helpers own only the exact namespace/mount operation. Tools publication owns unpublished immutable content and Docker reference publication; it does not interpret arbitrary guest instructions as host code. No package installer or separate local-service container is introduced.

## API Shape

[Specification public surfaces](spec.md#public-surface) own exposed behavior; the tools contract owns storage and transaction shape. `docker/home-overlays.conf` supplies the current internal path-pair policy. Internal function names and fixture implementations are not additional public APIs.

## Workflow And Data Flow

The intended construction flow is reviewed signature file → offline validation and derived manifest → acquisition and method-specific signature checks → verified local installation → validated tools/runtime artifacts → Docker publication. Verification failure stops before the affected artifact is consumed. Start flows from inspected Docker state through M-01 ownership and M-04 mounts to M-03 services. Guest writes flow to declared host data or workspace uppers. Explicit acceptance flows through paused capture and isolated publication to a new shared reference while leaving the guest intact. Restore flows through exclusive storage proof, bounded clear, and same-container restart. Cleanup consumes complete resource references before any candidate deletion.

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
- Preserve every shipped tool, managed runtime compatibility lines, mounted-default selection, and retained schema-1 manifest validation; new construction binds its complete signature file and subordinate native inputs.
- Preserve actual capability/seccomp/NNP controls and explicit guest administration while reducing unnecessary authority through evidenced changes.

## Failure Modes

Required Docker ownership, mount, lineage, and reference validations refuse dependent mutation when their evidence is unavailable or conflicting. Restore's initial recipe-image probe currently skips publication comparison on inspection failure, so it does not realize the hardened fail-closed requirement for that observation. Build failure retains published artifacts. Snapshot failure attempts same-container resume and removes owned host temporaries. Publication may leave an unselected complete candidate but does not clear the live stage. Failed restore attempts same-container restart and remains failed. Neither failure nor a clean stage supplies permission to remove host mounts or unknown resources.

Current gaps in complete input verification, secret exclusion, vulnerability coverage, and helper minimization remain requirements at the [specification](spec.md#release-security). The selected locked-acquisition architecture is not evidence of implementation or complete verified construction. Missing exact versions or publisher proofs remain artifact-specific gaps; they cannot authorize fabricated hashes, a weaker acquisition route, or removal of capabilities.

## Acceptance Criteria

- Existing command and mount tests preserve protected host lowers, literal inputs, owned-resource validation, and refused unsafe mappings.
- Tools-state and native publication tests preserve guest identity and filesystem through acceptance/restore and their failure paths.
- Build/cache and sharing tests distinguish changed manifests, source recipes, modes, working folders, and referenced artifacts.
- Locked-acquisition checks exercise the real loader and acquisition/install boundary with accepted and corrupt inputs, forbid ordinary release discovery including update notices, preserve offline legacy validation, and verify dependency/hook refusal before execution. Native image construction remains a separately evidenced integration claim.
- Cleanup tests retain stopped/image references, accepted data, and unknown lineage.
- Security acceptance additionally requires the specification's intended containment, secret, input-verification, and release evidence; source configuration alone does not establish those effects.
