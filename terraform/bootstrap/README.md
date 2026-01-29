# Bootstrap Infrastructure

This directory contains the Terraform configuration for the long-lived resources required to connect GitHub Actions to Google Cloud.

**Resources:**
*   Workload Identity Pool & Provider
*   Service Account for CI/CD
*   IAM Roles

**Setup:**
Run this once manually to bootstrap the environment.

```bash
cd terraform/bootstrap
terraform init -backend-config="bucket=<YOUR_STATE_BUCKET>" -backend-config="prefix=terraform/bootstrap"
terraform apply -var="project_id=<YOUR_PROJECT_ID>"
```
