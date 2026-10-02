# Terraform: Pilot-stage reference starter

This used to be a plain checklist. It is now a worked (but still
intentionally minimal) AWS starter for the "Pilot" stage of
[`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md)'s deployment evolution:
regional VPC, managed PostgreSQL, managed Redis, encrypted object storage
and a KMS key, all on private networking.

| File | What it defines |
| --- | --- |
| `versions.tf` | Terraform/provider version pins. Configure your own remote state backend here before real use. |
| `variables.tf` | Project name, environment, region, AZs, instance sizing. |
| `main.tf` | VPC, KMS key, S3 document bucket, RDS PostgreSQL, ElastiCache Redis, and the security groups that keep the database/cache private-only. |
| `outputs.tf` | IDs/endpoints you need to wire into `services/api`'s `DATABASE_URL` / `REDIS_URL` and into the Kubernetes manifests in `../kubernetes`. |

## What this is not

- **Not production-certified.** Review sizing (`variables.tf` defaults are
  small/cheap on purpose), the single shared NAT gateway, backup windows,
  multi-region/DR posture and IAM boundaries against your own compliance
  requirements before applying this anywhere real.
- **Not multi-cloud.** This is a worked AWS example so there is something
  concrete to review instead of a text list. The original list of
  recommended capability areas still holds for Azure/GCP — swap the
  provider block in `versions.tf` and the resources in `main.tf` for their
  Azure (VNet / Azure Database for PostgreSQL / Azure Cache for Redis / Key
  Vault) or GCP (VPC / Cloud SQL / Memorystore / Cloud KMS) equivalents.
- **Not a Kubernetes/compute layer.** Regional Kubernetes (EKS/AKS/GKE),
  the WAF/load balancer in front of it and private DNS are still open
  "Enterprise" stage items — see `docs/ARCHITECTURE.md` section 10 and
  `docs/SECURITY.md`'s production backlog.

## Using it

```bash
cd infra/terraform
terraform init      # after configuring a remote state backend in versions.tf
terraform validate
terraform plan
```

`terraform validate` is also run by hand during review; it does not require
cloud credentials, only network access to the Terraform/module registries.
`terraform plan`/`apply` do require AWS credentials and real backend
configuration and are intentionally not part of CI.
