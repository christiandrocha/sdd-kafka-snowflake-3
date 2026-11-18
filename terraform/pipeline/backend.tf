# Same bucket as terraform/platform, separate state (Decision 1, Decision 12):
#   terraform init -backend-config="bucket=<state-bucket>" -backend-config="region=<aws-region>"
terraform {
  backend "s3" {
    key          = "sdd-kafka-snowflake-3/pipeline.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}
