> **Language / 语言**: English · [简体中文](DATA_GOVERNANCE.zh-CN.md)

# Data Governance

The repository uses synthetic data only, including every V2.0 digital-twin geometry reference, sensor reading and scenario.

Production policy should classify data by:

- tenant and project;
- jurisdiction;
- confidentiality level;
- personal data status;
- client/employer restrictions;
- export/cross-border restriction;
- retention period.

Recommended architecture: global metadata in the control plane, sensitive project content retained in the designated regional data plane whenever contractual or legal obligations require it.

## Digital-twin governance

- A `Twin ID` is stable and source-neutral; source-system identifiers remain aliases.
- Every state transition records source, effective time, evidence and confidence.
- Model version, coordinate reference system and geometry reference are explicit metadata.
- Telemetry is time-bound and must never silently overwrite engineering design truth.
- AI simulations are separate from actual state; only approved actions may create operational changes.
- Project/tenant authorization must be applied at object, document, telemetry and scenario boundaries before production use.
