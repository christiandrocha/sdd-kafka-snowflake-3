# Runbook — Terraform state bootstrap (AWS S3 + GitHub OIDC)

**When:** once, before the first `terraform.yml` run (Day 3), and again when the project moves to a
new AWS account.
**Who:** the owner, by hand. Agents never run these commands. This is a documented manual step,
**not** a Terraform root (owner decision 2026-11-18, COST_GOVERNANCE build run 4).
**Why manual:** the state bucket has to exist before any Terraform can store state in it. REQ-01
covers Snowflake objects; these AWS objects sit outside the Snowflake budget (DESIGN Decision 12,
*Integration points*).

What it creates:

| Object | Purpose |
|--------|---------|
| S3 bucket `<STATE_BUCKET>` | Terraform state for `terraform/platform` and `terraform/pipeline`. Native lock files, no DynamoDB (Decision 12) |
| IAM OIDC provider `token.actions.githubusercontent.com` | Lets GitHub Actions get short-lived AWS credentials. No static keys |
| IAM role `sdd3-tfstate-plan` | Assumed only by jobs in environment **`snowflake-plan`**. Reads state, writes lock files only |
| IAM role `sdd3-tfstate-apply` | Assumed only by jobs in environment **`snowflake-dev`**. Reads and writes state and lock files |

Two roles instead of one: the PR plan job never gets write access to the state.

Placeholders: `<AWS_ACCOUNT_ID>`, `<STATE_BUCKET>` (globally unique), `<REGION>` (suggested
`sa-east-1`, the same region as the Snowflake account). The state keys are fixed by
`terraform/*/backend.tf`: `sdd-kafka-snowflake-3/platform.tfstate` and
`sdd-kafka-snowflake-3/pipeline.tfstate`.

---

## 1. Bucket

**Versioning is mandatory.** It is the only way to recover a state file that a bad apply or a
human error overwrote. HashiCorp: "enable Bucket Versioning on the S3 bucket". Never suspend it.

```bash
aws s3api create-bucket --bucket <STATE_BUCKET> --region <REGION> \
  --create-bucket-configuration LocationConstraint=<REGION>

# Mandatory: versioning
aws s3api put-bucket-versioning --bucket <STATE_BUCKET> \
  --versioning-configuration Status=Enabled

# Encryption at rest (SSE-S3; no KMS key, so no KMS permissions are needed)
aws s3api put-bucket-encryption --bucket <STATE_BUCKET> \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":true}]}'

# No public access, ever
aws s3api put-public-access-block --bucket <STATE_BUCKET> \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

# Bucket owner owns every object; ACLs disabled
aws s3api put-bucket-ownership-controls --bucket <STATE_BUCKET> \
  --ownership-controls '{"Rules":[{"ObjectOwnership":"BucketOwnerEnforced"}]}'
```

Bucket policy: TLS only.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyInsecureTransport",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": ["arn:aws:s3:::<STATE_BUCKET>", "arn:aws:s3:::<STATE_BUCKET>/*"],
      "Condition": {"Bool": {"aws:SecureTransport": "false"}}
    }
  ]
}
```

```bash
aws s3api put-bucket-policy --bucket <STATE_BUCKET> --policy file://bucket-policy.json
```

Check:

```bash
aws s3api get-bucket-versioning --bucket <STATE_BUCKET>        # "Status": "Enabled"  ← required
aws s3api get-public-access-block --bucket <STATE_BUCKET>      # all four true
```

## 2. GitHub OIDC provider (once per AWS account)

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com
```

## 3. Roles — trust restricted to this repository and one environment each

A job that declares `environment:` gets an OIDC `sub` claim of the form
`repo:OWNER/REPO:environment:NAME` (GitHub docs, *Configuring OpenID Connect in Amazon Web
Services*). Each trust policy accepts exactly one such `sub` with `StringEquals`, not
`StringLike`. Other repositories, other environments, and jobs without an environment cannot
assume the role.

`trust-plan.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::<AWS_ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          "token.actions.githubusercontent.com:sub": "repo:christiandrocha/sdd-kafka-snowflake-3:environment:snowflake-plan"
        }
      }
    }
  ]
}
```

`trust-apply.json`: identical except
`"token.actions.githubusercontent.com:sub": "repo:christiandrocha/sdd-kafka-snowflake-3:environment:snowflake-dev"`.

## 4. Permissions — the minimum for the S3 backend with `use_lockfile = true`

HashiCorp, *S3 backend*: the backend needs `s3:ListBucket` on the bucket, `s3:GetObject` and
`s3:PutObject` on the state key, and "if use_lockfile is set, s3:GetObject, s3:PutObject, and
s3:DeleteObject are required on the lock file" (`<key>.tflock`). `s3:DeleteObject` is **not**
needed on the state file.

`policy-apply.json` (role `sdd3-tfstate-apply`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListStatePrefix",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::<STATE_BUCKET>",
      "Condition": {"StringLike": {"s3:prefix": ["sdd-kafka-snowflake-3/*"]}}
    },
    {
      "Sid": "ReadWriteState",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject"],
      "Resource": [
        "arn:aws:s3:::<STATE_BUCKET>/sdd-kafka-snowflake-3/platform.tfstate",
        "arn:aws:s3:::<STATE_BUCKET>/sdd-kafka-snowflake-3/pipeline.tfstate"
      ]
    },
    {
      "Sid": "ManageLockFiles",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": [
        "arn:aws:s3:::<STATE_BUCKET>/sdd-kafka-snowflake-3/platform.tfstate.tflock",
        "arn:aws:s3:::<STATE_BUCKET>/sdd-kafka-snowflake-3/pipeline.tfstate.tflock"
      ]
    }
  ]
}
```

`policy-plan.json` (role `sdd3-tfstate-plan`): the same three statements, except **`ReadWriteState`
becomes `ReadState` with `s3:GetObject` only**. A plan reads the state and takes a lock; it never
writes the state.

```bash
aws iam create-role --role-name sdd3-tfstate-plan  --assume-role-policy-document file://trust-plan.json
aws iam create-role --role-name sdd3-tfstate-apply --assume-role-policy-document file://trust-apply.json
aws iam put-role-policy --role-name sdd3-tfstate-plan  --policy-name tfstate --policy-document file://policy-plan.json
aws iam put-role-policy --role-name sdd3-tfstate-apply --policy-name tfstate --policy-document file://policy-apply.json
```

Set `--max-session-duration` only if a job ever needs more than the default 1 h. None does today.

## 5. GitHub configuration

**Repository → Settings → Environments**

| Environment | Protection | Deployment branches |
|-------------|------------|---------------------|
| `snowflake-plan` | none (PRs get a plan automatically — Decision 11) | no restriction (PR refs) |
| `snowflake-dev` | **required reviewer: the owner** | **`main` only** |

**Variables and secrets.** These are names only; the values never go in the repository.
`terraform.yml`'s header lists the same names.

| Where | Kind | Name | Value |
|-------|------|------|-------|
| repository | variable | `SNOWFLAKE_ACCOUNT` | `GWHUBCF-QQ53235` |
| repository | variable | `TF_STATE_BUCKET` / `TF_STATE_REGION` | `<STATE_BUCKET>` / `<REGION>` |
| repository | variable | `DAGSTER_RSA_PUBLIC_KEY`, `DATA_AGENTS_RSA_PUBLIC_KEY`, `CURSOR_RSA_PUBLIC_KEY` | public keys, one line, no header (O4) |
| `snowflake-plan` | variable | `SNOWFLAKE_USER` | `TERRAFORM_PLAN_SVC` |
| `snowflake-plan` | variable | `AWS_ROLE_ARN` | `arn:aws:iam::<AWS_ACCOUNT_ID>:role/sdd3-tfstate-plan` |
| `snowflake-plan` | secret | `SNOWFLAKE_PRIVATE_KEY` | `TERRAFORM_PLAN_SVC` private key (PEM) |
| `snowflake-dev` | variable | `SNOWFLAKE_USER` | `TERRAFORM_SVC` |
| `snowflake-dev` | variable | `SNOWFLAKE_PLAN_USER` | `TERRAFORM_PLAN_SVC` (`verify_governance.sql` runs read-only) |
| `snowflake-dev` | variable | `AWS_ROLE_ARN` | `arn:aws:iam::<AWS_ACCOUNT_ID>:role/sdd3-tfstate-apply` |
| `snowflake-dev` | secret | `SNOWFLAKE_PRIVATE_KEY` | `TERRAFORM_SVC` private key (PEM) |
| `snowflake-dev` | secret | `SNOWFLAKE_PLAN_PRIVATE_KEY` | `TERRAFORM_PLAN_SVC` private key (PEM) |
| `snowflake-dev` | secret | `BUDGET_NOTIFY_EMAIL` | owner's verified e-mail. A **secret**, not a variable: variables are printed unmasked in the logs of this public repository |

## 6. Verify

1. Open a PR that touches `terraform/`. The `plan (read-only)` job must reach `terraform init`
   with the backend. `AccessDenied` there means the plan role's trust or policy is wrong.
2. In the AWS console, CloudTrail `AssumeRoleWithWebIdentity` events must show
   `sdd3-tfstate-plan` for PRs and `sdd3-tfstate-apply` only for `main` runs.
3. After the first apply: `aws s3api list-object-versions --bucket <STATE_BUCKET> --prefix sdd-kafka-snowflake-3/`
   lists versions of `platform.tfstate`. That confirms versioning took effect.

## Recovering a state file

```bash
aws s3api list-object-versions --bucket <STATE_BUCKET> --prefix sdd-kafka-snowflake-3/platform.tfstate
aws s3api get-object --bucket <STATE_BUCKET> --key sdd-kafka-snowflake-3/platform.tfstate \
  --version-id <VERSION_ID> platform.tfstate.recovered
```

Inspect the recovered file before uploading it back. Restoring an old state makes Terraform
"forget" objects it created afterwards, so read the next plan carefully.
