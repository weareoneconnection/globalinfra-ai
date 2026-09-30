# Data Governance

V1.0 uses synthetic data only.

Production policy should classify data by:

- tenant and project;
- jurisdiction;
- confidentiality level;
- personal data status;
- client/employer restrictions;
- export/cross-border restriction;
- retention period.

Recommended architecture: global metadata in the control plane, sensitive project content retained in the designated regional data plane whenever contractual or legal obligations require it.
