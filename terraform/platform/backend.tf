# Terraform state in S3 with native locking, no DynamoDB (Decision 12).
# Bucket and region are passed at init time so they never live in a public repo:
#   terraform init -backend-config="bucket=<state-bucket>" -backend-config="region=<aws-region>"
# CI authenticates to AWS with OIDC, not static keys.
terraform {
  backend "s3" {
    key          = "sdd-kafka-snowflake-3/platform.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}
