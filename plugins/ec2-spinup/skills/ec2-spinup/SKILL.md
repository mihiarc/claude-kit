---
name: ec2-spinup
description: Provision a small EC2 worker in a specific AWS region for in-region AWS work (S3-to-S3 copies, throwaway compute, region-local data moves) with safe defaults — instance-profile auth (no copied keys), IP-restricted SSH, IMDSv2-only, shutdown-terminate. Walks pre-flight perm/resource discovery, the launch, post-launch verification, and resource tracking for cleanup. Triggers on "spin up an EC2", "need a worker in us-west-2/etc.", "in-region S3 copy needs an instance", or any ad-hoc throwaway-compute request that benefits from running inside AWS rather than from a laptop.
---

# ec2-spinup

Provision a temporary EC2 worker with safe defaults for ad-hoc AWS work. The "why" is almost always: the work needs to run *inside* AWS (in-region transfer speed, low latency to a service, an instance profile instead of long-lived keys, or a long-running process that shouldn't depend on a laptop staying open).

## Inputs to clarify with the user (or infer from context)

Before any AWS calls, you need to know:

1. **Region.** Pinned by where the data/service lives. Don't guess — confirm. The whole point of using EC2 is staying in-region.
2. **What AWS resources the instance must access.** Drives the IAM auth decision. List them concretely (bucket ARNs, table ARNs, etc.).
3. **Connection model.** SSH (key pair + SG inbound 22) or SSM Session Manager (no inbound, but requires `AmazonSSMManagedInstanceCore` on the instance role). Default to SSM if it's available; SSH otherwise.
4. **Lifetime.** Hours? Days? Affects whether you bother with `--instance-initiated-shutdown-behavior terminate`. For one-shot work, always set it.

## Procedure

### Step 1 — Identity and pre-flight

Run these in parallel; you need the answers to make decisions later:

```
# Confirm CLI identity and region
aws sts get-caller-identity
aws configure list

# Default VPC + a public-IP-assigning subnet in the target region
aws ec2 describe-vpcs --filters Name=isDefault,Values=true \
  --query 'Vpcs[0].{VpcId:VpcId, CidrBlock:CidrBlock}'
aws ec2 describe-subnets --filters Name=vpc-id,Values=<VPC_ID> \
  --query 'Subnets[?MapPublicIpOnLaunch==`true`][0:3].{SubnetId:SubnetId, AZ:AvailabilityZone}'

# Latest Amazon Linux 2023 x86_64 AMI in this region
# (SSM public params are the canonical source, but require ssm:GetParameter — use
# describe-images as a fallback that only needs ec2:DescribeImages.)
aws ec2 describe-images --owners amazon \
  --filters "Name=name,Values=al2023-ami-2023.*-kernel-*-x86_64" \
            "Name=state,Values=available" "Name=architecture,Values=x86_64" \
  --query 'sort_by(Images, &CreationDate)[-1].{ImageId:ImageId, Name:Name}'

# Your current public IP (for SSH SG rule, if going SSH route)
curl -sS https://checkip.amazonaws.com
```

Record the answers. They feed the launch command.

### Step 2 — Choose the IAM auth pattern (read-only; create nothing yet)

Decision tree (try each in order; stop at the first that works). This step only *decides* —
any role or instance profile is created in Step 3, after the Step 2b confirmation.

**A. Create a scoped instance role.** The "right" answer if you have `iam:CreateRole` (check with
`aws iam simulate-principal-policy` or by the user's known permissions, not by trying it). Draft
the trust policy (`Service: ec2.amazonaws.com`) and an inline policy with only the actions and
resources the work needs, plus `AmazonSSMManagedInstanceCore` if SSM is desired. EC2 attaches a
role through an **instance profile**, so this option also means creating one (Step 3).

**B. Reuse an existing role.** If `CreateRole` is denied (common on developer-tier IAM users), survey existing roles:
```
aws iam list-roles --query 'Roles[*].RoleName' --output text
# For each candidate name:
aws iam get-role --role-name <NAME> --query 'Role.AssumeRolePolicyDocument'
aws iam list-attached-role-policies --role-name <NAME>
aws iam list-role-policies --role-name <NAME>
```
The candidate must (1) trust `ec2.amazonaws.com` and (2) have the actions you need. If `iam:GetInstanceProfile` is also denied, sidestep by checking what existing instances use:
```
aws ec2 describe-instances \
  --query 'Reservations[*].Instances[?IamInstanceProfile != null].IamInstanceProfile.Arn' \
  --output text | tr '\t' '\n' | sort -u
```
Tradeoffs to surface to the user when picking a too-broad existing role: blast radius widens (the role's perms apply to anything else inheriting it), and you may have to settle for SSH if SSM perms aren't on the role.

**C. Escalate.** If no existing role fits, ask whoever owns the AWS account to either grant `iam:CreateRole` (scoped to a prefix), attach `AmazonSSMManagedInstanceCore` to an existing role, or create a new role from a spec you provide. Draft the spec; don't make them write it.

**Always present the trade-offs to the user before picking an option that compromises least-privilege.**

### Step 2b — Confirm the launch plan with the user (always, before any create call)

**Nothing is created — no IAM role, instance profile, key pair, security group or instance —
until the user has confirmed this plan in this session.** Present it in one message:

- Region, AZ/subnet, AMI, instance type, and the rough cost (see the cost note below).
- The auth pattern from Step 2. For option A, the exact trust policy and inline policy JSON and
  the role / instance-profile names you will create; for B, the existing role and its trade-offs.
- Connection model and, for SSH, the security-group CIDR (`<USER_IP>/32`).
- The full tag set as key=value pairs: the account's standard cost-allocation keys plus `Name` and
  `auto-terminate`. When a skill or doc in reach defines the account's tagging standard, take the
  keys and values from it rather than guessing; never invent a project or owner value.
- The teardown sequence you will hand back (Cleanup below).

Wait for the user to confirm or correct it. Do this even when the values seem obvious from the
repo or a previous run: a tag value is a permanent column in every future cost report, and an
IAM role outlives the instance unless someone deletes it. The same confirmed tag set goes on
every resource you create: role, instance profile, key pair, security group, instance, volume
and ENI.

### Step 3 — Provision: IAM (option A only), key pair, security group, instance

Naming convention: prefix everything with the project name (`<proj>-ec2`, `<proj>-ssh`,
`<proj>-worker-role`, `Name=<proj>-worker`). Tag rules and values come from the
account's tagging standard; the confirmed set from Step 2b is written once as shell variables
and reused, so every resource carries every key.

```
# The tag set confirmed in Step 2b, written once.
T_PROJ=<project_name>; T_APP=<application_name>; T_COMP=<component>
T_OWNER=<owner>; T_FUND=<funding_source>
TAGS="{Key=project_name,Value=$T_PROJ},{Key=application_name,Value=$T_APP},{Key=component,Value=$T_COMP},{Key=owner,Value=$T_OWNER},{Key=funding_source,Value=$T_FUND},{Key=auto-terminate,Value=true}"
IAM_TAGS="Key=project_name,Value=$T_PROJ Key=application_name,Value=$T_APP Key=component,Value=$T_COMP Key=owner,Value=$T_OWNER Key=funding_source,Value=$T_FUND Key=auto-terminate,Value=true"

# IAM (option A only): role + inline policy + instance profile. trust.json and access.json
# are the policies the user confirmed in Step 2b, written to the scratchpad. EC2 attaches a
# role only through an instance profile, and a new profile can take ~10 s to be usable.
aws iam create-role --role-name <proj>-worker-role \
  --assume-role-policy-document file://trust.json --tags $IAM_TAGS
aws iam put-role-policy --role-name <proj>-worker-role \
  --policy-name <proj>-worker-access --policy-document file://access.json
# (SSM only) aws iam attach-role-policy --role-name <proj>-worker-role \
#   --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam create-instance-profile --instance-profile-name <proj>-worker-profile --tags $IAM_TAGS
aws iam add-role-to-instance-profile --instance-profile-name <proj>-worker-profile \
  --role-name <proj>-worker-role
aws iam wait instance-profile-exists --instance-profile-name <proj>-worker-profile
# Option B: skip this block and use the existing role's instance profile name below.

# Key pair (SSH route only). ED25519 over RSA. AWS returns the private key
# ONCE in the response — save it immediately, chmod 600.
KEY_PATH="$HOME/.ssh/<proj>-ec2.pem"
[ -f "$KEY_PATH" ] && { echo "KEY EXISTS — refusing to overwrite"; exit 1; }
aws ec2 create-key-pair --key-name <proj>-ec2 --key-type ed25519 \
  --tag-specifications "ResourceType=key-pair,Tags=[$TAGS]" \
  --query KeyMaterial --output text > "$KEY_PATH"
chmod 600 "$KEY_PATH"

# Security group (SSH route): port 22 from the user's current IP only.
# Never 0.0.0.0/0. If they roam between networks, edit the rule when their IP changes.
# (SSM route: create the group with no ingress rule at all.)
SG_ID=$(aws ec2 create-security-group \
  --vpc-id <VPC_ID> \
  --group-name <proj>-ssh \
  --description "<purpose, owner>" \
  --tag-specifications "ResourceType=security-group,Tags=[$TAGS]" \
  --query GroupId --output text)
aws ec2 authorize-security-group-ingress --group-id "$SG_ID" \
  --protocol tcp --port 22 --cidr <USER_IP>/32

# Launch. Instance-profile auth (NOT --user-data with keys), IMDSv2 only,
# shutdown=terminate so `sudo shutdown -h now` from inside cleans up the box.
# SSM route: drop --key-name.
aws ec2 run-instances \
  --image-id <AMI_ID> \
  --instance-type t3.micro \
  --key-name <proj>-ec2 \
  --security-group-ids "$SG_ID" \
  --subnet-id <SUBNET_ID> \
  --iam-instance-profile Name=<proj>-worker-profile \
  --metadata-options 'HttpTokens=required,HttpPutResponseHopLimit=1' \
  --instance-initiated-shutdown-behavior terminate \
  --tag-specifications \
    "ResourceType=instance,Tags=[{Key=Name,Value=<proj>-worker},$TAGS]" \
    "ResourceType=volume,Tags=[$TAGS]" \
    "ResourceType=network-interface,Tags=[$TAGS]"

# Wait for running and get public IP
aws ec2 wait instance-running --instance-ids <INSTANCE_ID>
aws ec2 describe-instances --instance-ids <INSTANCE_ID> \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text
```

Notes on the launch flags:
- `t3.micro` is the right default for I/O-bound CLI work like `aws s3 cp`. Bump up only if there's a real reason.
- Default 8 GB gp3 EBS is fine unless the work writes large local files (S3-to-S3 copy doesn't touch local disk).
- Don't set a public IP explicitly; the public-IP-assigning subnet from Step 1 handles it.

### Step 4 — Verify

Don't declare done until the instance proves it can do the job. SSH (or SSM) in, then:

```
# Confirms instance role is assumed, not user keys
aws sts get-caller-identity
# Confirms tooling
aws --version && python3 --version
# Confirms access to the actual resources you provisioned for
aws s3 ls s3://<bucket-the-instance-is-meant-to-touch>/ | head
```

If `get-caller-identity` returns a user ARN instead of `assumed-role/.../i-...`, the instance profile didn't attach correctly — investigate before proceeding.

The first SSH attempt may fail because cloud-init is still running. Retry every 15s for ~90s before giving up.

### Step 5 — Track resources for cleanup

Save the resource IDs immediately, to a project memory file (preferred when running in Claude Code with memory) or a scratch file outside the repo. Don't commit them: public IPs, key paths and instance IDs don't belong in git history. Capture:

- Instance ID
- Public IP and DNS (note these are ephemeral if the instance is stopped/started)
- Region, AZ, subnet, VPC, AMI, instance type
- Key pair name + local .pem path
- Security group ID + the CIDR it allows
- Instance profile / role name attached, and whether you created them (option A) or reused them
- Reconnect command
- The exact teardown sequence (below)

### Cleanup pattern (give to the user, run when done)

Order matters: SG can't be deleted while attached to a running instance, and a role can't be deleted while it's in an instance profile or still has policies.

```
aws ec2 terminate-instances --instance-ids <INSTANCE_ID>
aws ec2 wait instance-terminated --instance-ids <INSTANCE_ID>
aws ec2 delete-security-group --group-id <SG_ID>
aws ec2 delete-key-pair --key-name <proj>-ec2
rm ~/.ssh/<proj>-ec2.pem

# Only if you created the role and profile in Step 3 (option A) — never delete a reused role.
aws iam remove-role-from-instance-profile --instance-profile-name <proj>-worker-profile \
  --role-name <proj>-worker-role
aws iam delete-instance-profile --instance-profile-name <proj>-worker-profile
aws iam delete-role-policy --role-name <proj>-worker-role --policy-name <proj>-worker-access
# (SSM only) aws iam detach-role-policy --role-name <proj>-worker-role \
#   --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam delete-role --role-name <proj>-worker-role
```

Cost note for the user: a running t3.micro is roughly $0.0104/hr (~$0.25/day) outside Free Tier. Stopped instances incur no compute cost but EBS volumes still bill (~$0.08/GB/mo for gp3 — about $0.02/day for 8 GB). For one-shot work, terminate, don't stop.

## Safety guardrails — non-negotiable defaults

These are not opinions. Don't skip them without explicit user opt-out:

1. **Same region as the data.** EC2 in us-east-1 doing `aws s3 cp` to a us-west-2 bucket transfers across regions and defeats the purpose.
2. **`--metadata-options HttpTokens=required`** — IMDSv2 only. Closes a known SSRF class.
3. **`--instance-initiated-shutdown-behavior terminate`** for ad-hoc workers. Makes "I'm done" a one-command action.
4. **Security group: SSH from current IP only**, never `0.0.0.0/0`. If SSM is available, no inbound rules at all.
5. **Instance-profile auth**, never `aws configure` with the user's access keys on the box. Long-lived creds on shared compute is the antipattern that instance profiles exist to fix.
6. **Fresh project key pair**, not the user's general SSH identity. Scoped to the project, deletable at cleanup.
7. **Tag everything** with the confirmed tag set plus `auto-terminate=true` — on the instance, its volume, its ENI, and every other resource you create. Untagged AWS resources are how cloud bills compound forever. When a skill or doc defines the account's tagging standard, follow it rather than restating it here.
8. **Confirm before creating anything**, IAM included (Step 2b), and hand back a teardown that removes everything you created.

## When this skill is the wrong tool

- The work is short and laptop-friendly (e.g., a one-time CLI call that finishes in under a minute). Don't EC2 a curl.
- The user already has bastion/jumphost infrastructure. Use that instead of provisioning new boxes.
- The work needs persistent state, scaling, scheduling, or a network address that doesn't change. That's an ECS/Fargate/Lambda/EC2 ASG conversation, not an ad-hoc worker.
- The user is unfamiliar with AWS billing. Surface the cost and cleanup path explicitly before launching anything.
