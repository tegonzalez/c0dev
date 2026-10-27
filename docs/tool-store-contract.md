---
doc-graph: "When there is an intention to amend this document, first Adhere to [dc-doc-contract]; otherwise, do not modify."
---

# c0dev Tool-Store Contract

| Metadata      | Value                    |
| ------------- | ------------------------ |
| Contract kind | immutable-snapshot-stage |
| Visibility    | public                   |

## Purpose

Fix the immutable tools-storage, identity, selection, stage, publication, restoration, and collection seam owned by the tools-store module in [design](design.md#module-inventory). This contract describes the current Docker-derived selection model; it does not create a package manager or a persistent checkout selector.

## Terminology

| Term                | Meaning                                                                                 |
| ------------------- | --------------------------------------------------------------------------------------- |
| Tools recipe        | Comment-stripped base/tools Dockerfile identity.                                        |
| Release manifest    | Canonical resolved toolchain JSON captured for a build.                                 |
| Complete payload    | Tools directory with its completeness marker written after payload and provenance.      |
| Published reference | Docker image labels binding mode, recipe, runtime build, tools payload, and base image. |
| Tools stage         | Configured tool-home upper and work directories; launcher upper is separate.            |

## Store Grammar

```text
/tools/
  opt/<tools-id>/
    .c0dev-complete
    .c0dev-toolchain.json       # build payload provenance
    .c0dev-accepted-from        # accepted payload parent
    .c0dev-stage-sha256         # accepted archive identity
    .cargo/bin/
    .rustup/
    .local/
  tmp/<tools-id>.partial
  tmp/<tools-id>.next
```

`tools-id` is exactly 64 lowercase hexadecimal digits. A marker establishes completion, not authenticity or vulnerability clearance. Build reuse additionally requires valid provenance matching the resolved recipe and release manifest. Accepted payloads retain their parent and stage digest. Legacy and unknown content remains subject to conservative retention.

There is no persistent `pins/` or `state/` selector directory. The runtime receives only `opt/<tools-id>` at `/tools/current:ro`; other payloads and store metadata are absent from its mount view.

## Identity

Let `manifest-sha256` be SHA-256 of the exact canonical release-manifest bytes and `tools-recipe-id` the base/tools recipe hash. The build tools identity is:

```text
sha256("c0-toolchain-build-v1\n" + tools-recipe-id + "\n" + manifest-sha256 + "\n")
```

The runtime recipe also includes its runtime Dockerfile and copied build inputs; its build identity is distinct from the tools identity. Absolute working-folder paths do not participate in shared recipe/build identity. Mode partitions published artifacts and storage; mode/build/real-working-folder identifies a runtime, and mode/real-working-folder identifies persistent workspace storage.

For acceptance, hash the ordered archive-digest stream to obtain `stage-sha256`; the payload identity is:

```text
sha256("c0-tools-accept-v1\n" + parent-tools-id + "\n" + stage-sha256 + "\n")
```

Archive digests include captured content and metadata and are not a reproducible source lock. The derived runtime build identity uses the parent runtime's `c0dev.build` label and the accepted tools identity:

```text
sha256("c0-tools-accept-build-v1\n" + parent-runtime-build-id + "\n" + accepted-tools-id + "\n")
```

The actual parent image is separately selected by its inspected immutable Docker image ID as the derived image's `FROM` source. Image labels and recipe aliases publish the resulting selection through Docker.

## Roles And Authority

| Role                    | Network      | Read authority                                               | Write authority                                             |
| ----------------------- | ------------ | ------------------------------------------------------------ | ----------------------------------------------------------- |
| Runtime                 | Guest egress | Selected payload, declared host mounts                       | Container layer, declared writable mounts, workspace uppers |
| Overlay helper          | None         | Selected lower, host launcher lower, exact runtime namespace | Exact overlay mount and workspace upper/work                |
| Snapshot helper         | None         | Paused runtime's configured tool overlays                    | Private host archive stream                                 |
| Publisher               | None         | Complete parent and captured archives                        | Unpublished candidate, new complete tools payload           |
| Runtime-image publisher | None         | Verified parent runtime and accepted payload metadata        | Derived Docker runtime image and publication tags           |
| Collector               | None         | Container/image references and payload provenance            | Unreferenced positively identified rebuildable caches       |

Constructed-image filesystem content is copied from a never-started container with no tools-store mount. The fixed build-payload publisher receives that data read-only and the candidate store writable, runs without network, and never executes the copied content. Actual privilege profiles and their trust limits are explained by the [security model](security-model.md#process-variants). Guest identities receive no tools-volume writer or daemon socket.

## Stage Contract

The stage covers the complete configured tools upper, not a payload classifier. Launcher state is excluded from tools acceptance and restoration.

| Status | Meaning                                       |
| ------ | --------------------------------------------- |
| A      | Upper entry has no corresponding lower entry. |
| M      | Upper non-directory shadows a lower path.     |
| D      | Whiteout hides a lower path.                  |
| O      | Opaque directory hides lower directory data.  |

Default display may collapse additions but retains their count and non-additive changes. Detailed display enumerates every entry observable by the checker. Neither status nor a path-only report establishes that content is free of secrets.

## Accept Transition

```text
running + staged
  -> validate actual runtime ownership, mounts, tools, and metadata
  -> pause runtime and capture configured merged tool overlays
  -> resume the same runtime
  -> verify archive paths and derive accepted payload identity
  -> copy complete parent into unpublished candidate
  -> replace configured tool paths and record parent/archive identity
  -> normalize ownership and write completeness last
  -> publish a derived runtime image through Docker
  -> retain the running container, mounted lower, and writable stage
```

Acceptance does not remove the guest, clear its files, or change its fixed tools mount. A complete identical target can be reused; an incomplete existing target blocks publication. The current shared runtime publication becomes eligible for later creation. Starting a replacement build requires the workspace's existing runtime to be stopped so writable home storage is not mounted concurrently by incompatible builds.

## Restore Transition

```text
running + staged
  -> validate mounted tools and compare publication when recipe inspection succeeds
  -> prove exclusive ownership of the exact overlay volume
  -> stop the same container
  -> recheck references and clear only configured tool upper/work paths
  -> start and validate the same container
```

Current restore starts from the mounted tools identity. When its initial recipe-image inspection succeeds, it resolves publication and refuses a different tools identity or failed resolution before clearing; an absent recipe image or failed initial inspection skips this comparison. Another retained container referencing the stage still refuses clearing. This conditional probe does not establish the hardened fail-closed requirement in [containment](spec.md#containment). Restore retains the mounted payload, container filesystem, launcher upper, and direct host mounts. The discarded tool upper has no c0 recovery. A clear failure still attempts to resume the same guest and remains a failed operation.

## Build Transition

Construction resolves the release manifest, verifies declared version/security floors, builds and validates tools and runtime artifacts, and publishes the completed runtime image. Extraction copies the stopped constructed image into private host staging and uses fixed base-image code for candidate publication; constructed-image programs receive no writable store. Admitted root directories and the provenance path reject symlink redirection, while nested payload links remain literal copied links. Source-container cleanup requires the exact issued operation label and never-started state and uses its captured CID; no fixed-name container is removed as legacy cleanup. Payload and provenance are prepared under `.partial`; completeness precedes publication. A forced rebuild still referenced by a container remains under `.next` until safe promotion. Incomplete or mismatched staged provenance is not promotion authority. A failed build neither publishes its candidate runtime nor triggers success-path collection.

## Selection And Protection

Existing-runtime commands use the actual inspected container, image, mounts, and tools identity. New creation requires a validated Docker-published reference and refuses missing, conflicting, or unavailable required publication metadata; no saved default or pin supplies absent facts. Restore's publication comparison follows the conditional probe described above, so a failed initial recipe-image inspection is not demonstrated refusal on that path.

```text
protected := tools references from all running/stopped/recovery containers
             union tools references from all published runtime images
collectable := complete, verifiably rebuildable cache payloads
               with no protected reference
```

Accepted payloads and unknown legacy data are retained when rebuildability or ownership is unproved. Failure to enumerate references grants no deletion authority. Ordinary clean refuses while any container references the store. Whole-store removal also refuses published-image references and retained unknown data. Cleanup never removes host caches, projects, guest containers, or persistent home-overlay volumes.

## Failure Contract

- Capture failure attempts to resume the same paused guest and leaves its stage and parent payload intact.
- Publication failure preserves the complete parent, running guest, and writable stage; a completed orphan candidate may remain for diagnosis.
- Tools acceptance and restore never replace the guest filesystem.
- Required ownership, reference, mount, and build-provenance validations must succeed before their dependent effects. Restore's skipped comparison after initial recipe-image inspection failure remains a current gap against hardened fail-closed inspection.
- Rebuild, promotion, and collection preserve payloads still referenced by retained containers or published images.
- Secret-free and vulnerability-free release claims require the separate [release-security gate](spec.md#release-security), not this storage transaction.
