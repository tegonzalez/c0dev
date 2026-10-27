---
doc-graph: "When there is an intention to amend this document, first Adhere to [dc-doc-technical]; otherwise, do not modify."
---

# c0dev Security Model

## Purpose

Explain the trust boundaries of the current host launcher, development guest, durable mounts, helper processes, software inputs, and tools publication. [Specification containment](spec.md#containment), [private-data requirements](spec.md#private-data), and [release security](spec.md#release-security) own the required hardened baseline. Configuration and source observations below are not deployed-state verification or release clearance.

## Terminology

| Term                 | Meaning                                                                                                                          |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Guest administration | Explicit UID-0 execution inside the guest's existing restrictions.                                                               |
| Host authority       | Owning-account and Docker-daemon ability to change host resources and launch helpers.                                            |
| Tools publication    | Fixed host-controlled production of a new complete payload and derived runtime artifact.                                         |
| Secret               | Credential, private key, token, or private user content requiring restricted disclosure.                                         |
| Integrity proof      | Verification of exact input bytes against independently trusted expected content or supported native signature/repository proof. |

## Threat Model

| Boundary     | Scope                                                                                                                                           |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| In scope     | Compromised guest/agent/updater, accidental host-resource damage, credential disclosure, vulnerable embedded software, and authority expansion. |
| Out of scope | A malicious owning host account or Docker operator, or a compromised host/VM kernel.                                                            |
| Premise      | Docker and the platform enforce their declared isolation; host execution uses independently protected source.                                   |

This is a single-user development environment, not a multi-tenant sandbox. Deliberately writable host mounts are real host authority, and their contents are readable by guest code. A read-only mount removes a write route but does not protect confidentiality. Docker identifies daemon access and added capabilities as material security boundaries; see [Docker Engine security](https://docs.docker.com/engine/security/).

## Process Variants

The runtime policy is selected through `C0_SECURITY`: `guest-admin` (default) drops all capabilities and restores `CHOWN`, `DAC_OVERRIDE`, and `FOWNER`; `least-privilege` drops all capabilities and restores none. Both Compose profiles set `privileged: false`, use the vendored Moby default seccomp profile, and enable `no-new-privileges`. See [guest-admin Compose](../docker/docker-compose.security-guest-admin.yaml), [least-privilege Compose](../docker/docker-compose.security-least-privilege.yaml), and [host helper construction](../bin/c0). Actual restrictions require separate native observations.

| Kind                    | Identity and capabilities                                                              | Seccomp / privilege escalation        | Network              | Writable scope                                         |
| ----------------------- | -------------------------------------------------------------------------------------- | ------------------------------------- | -------------------- | ------------------------------------------------------ |
| Build                   | System setup root; user-tool installation dev                                          | Docker build profile                  | Declared acquisition | Build layers and unpublished payload                   |
| Runtime dev             | UID 1000; effective/permitted capabilities zero in observed runtime                    | Project seccomp; no-new-privileges    | Guest egress         | Container layer, declared writable host mounts, uppers |
| Explicit guest root     | UID 0; runtime bound includes CHOWN, DAC_OVERRIDE, FOWNER                              | Runtime profile; no-new-privileges    | Guest egress         | Same guest/host mount view; no publication             |
| Overlay helper          | UID 0; SYS_ADMIN, SYS_PTRACE, SYS_CHROOT, DAC_OVERRIDE, DAC_READ_SEARCH, CHOWN, FOWNER | Unconfined seccomp; no-new-privileges | None                 | Exact runtime mount namespace and overlay storage      |
| Snapshot helper         | UID 0; SYS_ADMIN, SYS_PTRACE, SYS_CHROOT, DAC_OVERRIDE, DAC_READ_SEARCH                | Unconfined seccomp; no-new-privileges | None                 | Owned host archive stream                              |
| Tools publisher         | UID 0; CHOWN, DAC_OVERRIDE, DAC_READ_SEARCH, FOWNER                                    | Read-only root; no-new-privileges     | None                 | Unpublished/new tools payload                          |
| Restore/GC helper       | UID 0; DAC_OVERRIDE, FOWNER for classified removal                                     | Fixed host helper; no-new-privileges  | None                 | Proven owned clear/cache paths                         |
| Derived-image publisher | Host-controlled Docker build                                                           | Parent image configuration retained   | None                 | New runtime image and Docker publication tags          |

Namespace mount and snapshot helpers bind the original helper root and proc directory by held descriptors before namespace entry; executable and loader resolution stays in that helper root. The guest root is only a data/mount target, not the source of privileged shell programs. Build payload extraction uses a never-started, store-less source container; only a fixed base-image publisher receives writable candidate access, with no network and only CHOWN, DAC_OVERRIDE, and FOWNER added to the dropped capability set.

Helper privileges and unconfined seccomp require operation-specific necessity evidence, not a claim that every process is capability-free. Guest-root administration remains supported without privileged containers or daemon access.

## Storage Boundaries

| Surface                          | Guest authority                                                 | Interpretation                                                                                                               |
| -------------------------------- | --------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Selected tools                   | Selected subpath read-only at `/tools/current`                  | Guest cannot modify lower content or browse other store paths through this mount.                                            |
| Tools upper/work                 | Workspace volume exposed through configured overlays            | Native tool writes persist across ordinary replacement; tools restore deliberately discards its scoped upper.                |
| Host launcher lower              | Read-only `/run/c0/host-bin`                                    | Guest launcher writes go to separate persistent upper, not host scripts.                                                     |
| Host control files               | Git configuration, entrypoint, overlay policy/checker read-only | Their integrity still depends on no writable alias or alternate host execution source.                                       |
| Configuration, caches, projects  | Declared host read/write mounts                                 | Required durability intentionally exposes these data to guest code.                                                          |
| Guest auth directory             | `auth/ssh` remains the durable writable guest SSH mount         | Holds server identity, public authorization, and guest SSH state; active and archived management client keys are outside it. |
| Host management identity/trust   | `auth/ssh-client` is absent from guest mounts                   | Private directory owns the active client key, known-hosts state, and retained legacy key archive.                            |
| Tools metadata and Docker socket | Absent from guest                                               | Host commands alone coordinate publication and collection.                                                                   |

Host path validation, symlink/alias handling, Docker attribution, and exact resource references must be considered together. A label or path prefix alone is insufficient authority for host deletion, signaling, or namespace entry. Storage preservation and publication rules belong to the [tools contract](tool-store-contract.md).

## Credentials And Observability

SSH key/config creation and Orca log access use descriptor-bound host I/O. Descendant symlinks, non-regular files, and multiply linked files refuse; config replacement and log reads/reset do not follow guest-selected host redirects. These checks preserve ordinary file contents and durability but are not secret-content classification; management client material is separately excluded from the guest directory.

The launcher parses optional host `auth/.env` as literal data without exporting its names or values into host controls. Docker receives an encoded environment envelope through a private pipe-backed env-file; SSH forwards only the private envelope fields in its child environment. A fixed guest bootstrap removes those fields and restores the requested guest environment before execution. Chunking preserves values larger than an env-file line, and the credential channel does not consume interactive stdin or echo a secret prefix through a TTY. Encoding is framing, not encryption: the intended recipient can inspect its environment, and the host SSH child briefly holds the encoded data.

Client logging is fixed below debug verbosity to avoid printing forwarded environment values. Generated server configuration admits only the private environment namespace plus ordinary locale; framework refusal messages contain no credential values. Invoked guest programs retain native output and can disclose their own environment, so this transport does not establish universal application-log or artifact secret exclusion.

Management private keys and host known-hosts state live in a mode-0700 host-only directory. Preparation creates a distinct fresh client identity, preserves server keys and unrelated authorizations, and retains observed legacy management material only in that private archive. Legacy matching uses the private key's native derived public identity, not a guest-writable sidecar. Managed legacy keys that cannot be read with their empty generation passphrase refuse retirement rather than prompting invisibly or guessing an identity. Already disclosed copies and other authorization identities remain separate concerns; moving files cannot erase prior disclosure.

The OrbStack agent relay exposes signing capability to the guest when enabled; `C0_SSH_AGENT=0` disables it. Keeping a key file on the host does not prevent guest use of a forwarded agent. Scope recipients and lifetime to the feature and avoid unnecessary forwarding.

The repository ignores `auth/` and common user-state paths. Ignore rules do not untrack committed content or establish that outgoing history, logs, build contexts, snapshots, and bundles contain no secrets. A detailed tools report lists paths, not secret-free contents. Actual secrets must never be reproduced to demonstrate a failure; verification uses synthetic values.

## Software Inputs And Release Evidence

The current resolver captures selected toolchain releases and enforces version/security floors. Some Dockerfile paths still execute upstream installers, resolve unconstrained dependencies, or install runtime assistant globals from floating selectors. Recipe hashes, final-version checks, and manifest equality identify selected inputs but do not authenticate every fetched or compiled byte.

The required release gate covers complete final content and build/helper execution inputs. Vulnerability inventory must account for OS packages, language dependencies, bundled interpreters, static native dependencies, vendored assets, and external installers. [OSV's image-scanning documentation](https://google.github.io/osv-scanner/usage/scan-image) describes OS/build-artifact identification in images; its [supported-artifact inventory](https://google.github.io/osv-scanner/supported-languages-and-lockfiles/) also makes coverage a concrete tooling question. Neither one scanner nor a clean lockfile report establishes full candidate coverage.

[CISA's Known Exploited Vulnerabilities catalog](https://www.cisa.gov/known-exploited-vulnerabilities-catalog) supplies exploitation evidence. It supplements vendor, distribution, and ecosystem advisories rather than defining the complete vulnerability set. Exact applicability, fixed/backported versions, and withdrawn findings require evidence; severity and convenience do not waive the specification's gate.

## Acceptance And Restore Boundaries

Runtime updaters retain guest filesystem/network authority and can alter declared writable host data. Networkless publication limits the publisher's egress and separates it from the running guest; it does not prove the submitted stage benign or free of private content. Capturing a paused view prevents ordinary guest writes during capture but is not cryptographic source provenance.

Acceptance publishes immutable tools and a derived runtime reference without replacing the running guest or clearing its stage. Restore stops and resumes the same guest and clears only tools state after selection/exclusivity proof. Launcher state and direct host data remain separate. Whole-stage capture can currently include non-XDG credentials, logs, or databases; that limitation does not authorize secret-bearing release artifacts.

## Network Exposure

SSH is loopback-published. The web service currently publishes a host port without a loopback-only address; `host.docker.internal` also reaches host services. Guest egress, service listeners, trusted X11 forwarding, and agent relay are separate access grants. The required narrow feature exposure is not established merely by the SSH binding or non-privileged UID.

## Assurance Limits

Current restore compares published selection only after a successful initial recipe-image inspection; absent/failed inspection skips that comparison in [the launcher](../bin/c0). It therefore does not demonstrate fail-closed publication inspection. This is a current implementation limit against the required hardened baseline, not permission to clear release assurance.

| Required property                | Current source evidence and remaining limit                                                                                                                                                 |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Minimum authority                | Runtime restrictions and separate fixed helper profiles exist; exhaustive feature-to-permission necessity and native per-role conformance are not established here.                         |
| Host containment                 | Protected launcher/control lowers and ownership-aware effects exist; declared writable data, host services, auth, agent access, and supported legacy layouts retain exposure.               |
| Input integrity                  | Canonical manifests and selected version/trust checks exist; executable installers, floating inputs, and transitive acquisitions lack complete origin-to-consumption proof.                 |
| Secret exclusion                 | Ignore patterns and scoped host workflows exist; argv-free scoped transport has regression evidence; complete application-log/history/context/snapshot/artifact exclusion remains unproved. |
| Vulnerability-free known content | No complete exact-artifact inventory, current advisory assessment, or enforced project release gate is supplied by this documentation change.                                               |
| Narrow network surface           | Loopback SSH exists; web publication, guest-to-host services, egress, and forwarding require separate scope verification.                                                                   |

These are requirements and bounded source observations, not findings that a live secret disclosure, host compromise, or particular CVE has occurred. Changes to controls require functional accepted/refused cases and preservation of durable mounts and supported guest administration. A missing required release assurance blocks clearance even when ordinary commands work.
