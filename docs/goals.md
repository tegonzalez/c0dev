---
doc-graph: "When there is an intention to amend this document, first Adhere to [dc-doc-goals]; otherwise, do not modify."
---

# c0dev Goals

- **G-01** Routine guest execution has the minimum permissions necessary for supported features and cannot administer the host. **Priority:** highest.
- **G-02** Canonical tools remain immutable to guest processes, including guest administration. **Priority:** highest.
- **G-03** Runtime tool changes remain durable across ordinary session replacement until deliberately discarded. **Priority:** high.
- **G-04** Construction of default tools remains distinct from disposition of runtime tool changes. **Priority:** high.
- **G-05** Operators can inspect and deliberately accept or discard the complete scope of runtime tool changes. **Priority:** high.
- **G-06** Runtime code cannot authorize publication of its own changes. **Priority:** high.
- **G-07** Scoped guest administration remains available within the guest security boundary. **Priority:** medium.
- **G-08** Commands and process variants are auditable for identity, privileges, mounts, network access, state effects, and verification. **Priority:** medium.
- **G-09** Equivalent reviewed construction inputs and resolved software selections produce identifiable, repeatable defaults. **Priority:** medium.
- **G-10** Declared host mounts preserve durable configuration and data across guest lifecycle operations.
- **G-11** Host commands preserve containment, host execution integrity, and unrelated user resources.
- **G-12** Releases contain no known applicable unremediated vulnerabilities, including actively exploited vulnerabilities.
- **G-13** Credentials, private keys, and private user data remain outside logs, version control, and unintended distribution.
- **G-14** Guest access to host data, services, and credentials is limited to the explicitly required feature surfaces.
- **G-15** Software consumed during construction and publication has traceable identity and verified integrity.
