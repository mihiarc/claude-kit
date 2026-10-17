---
name: ec2-spinup
description: Provision a small EC2 worker in a specific AWS region for in-region AWS work (S3-to-S3 copies, throwaway compute, region-local data moves) with safe defaults — instance-profile auth (no copied keys), SSH over SSM with no open ports (or SSH from the user's IP only), IMDSv2-only, shutdown-terminate, every resource tagged managed_by=claude-code. Checks which identity Claude is running as and whether it can actually connect before launching; Claude drafts any IAM change and the user applies it. Walks pre-flight discovery, the launch, verification, and resource tracking for cleanup. Triggers on "spin up an EC2", "need a worker in us-west-2/etc.", "in-region S3 copy needs an instance", or any ad-hoc throwaway-compute request that benefits from running inside AWS rather than from a laptop.
---

# ec2-spinup

Provision a temporary EC2 worker with safe defaults for ad-hoc AWS work. The "why" is almost always: the work needs to run *inside* AWS (in-region transfer speed, low latency to a service, an instance profile instead of long-lived keys, or a long-running process that shouldn't depend on a laptop staying open).

Two rules shape everything below:

- **IAM changes are the user's to apply.** Claude drafts every role, policy and grant and hands the user the exact commands; Claude never runs an IAM write itself, even when its credentials allow it, and never grants its own identity anything. An agent that can write IAM can widen its own access, so that one class of action keeps a human hand on it.
- **Everything Claude creates carries `managed_by=claude-code`.** That tag is what lets a dedicated agent role act only on resources Claude made (`references/agent-role.md`).

## Inputs to clarify with the user (or infer from context)

Before any AWS calls, you need to know:

1. **Region.** Pinned by where the data/service lives. Don't guess — confirm. The whole point of using EC2 is staying in-region.
2. **What AWS resources the instance must access.** Drives the instance role. List them concretely (bucket ARNs, table ARNs, etc.).
3. **Lifetime.** Hours? Days? Affects whether you bother with `--instance-initiated-shutdown-behavior terminate`. For one-shot work, always set it.

The connection model is decided by the pre-flight permission check in Step 1, not assumed.

## Procedure

### Step 1 — Identity and pre-flight

**Who is Claude running as?** Run `aws sts get-caller-identity` and read the ARN:

- `arn:aws:sts::<ACCT>:assumed-role/claude-agent/<session>` — the dedicated agent role. Its policy bounds what you can do; anything outside it (IAM, untagged resources) is a draft for the user.
- `arn:aws:iam::<ACCT>:user/<name>` or another human role — Claude is running on the user's own identity. Check whether it can write IAM (`iam:CreateRole`, `iam:AttachUserPolicy` in the simulation below). If it can, tell the user once, plainly: this session has IAM-admin rights, so the only thing stopping Claude from widening its own access is its own restraint; `references/agent-role.md` sets up a scoped identity. Then continue — the two rules above still hold.

**Can it do the plan, including connecting?** Simulate the actions before choosing anything. The simulator takes an IAM principal ARN: for an assumed role, convert `arn:aws:sts::<ACCT>:assumed-role/<ROLE>/<session>` to `arn:aws:iam::<ACCT>:role/<ROLE>` (add the role's path if it has one).

```
PRINCIPAL=<user or role ARN>
aws iam simulate-principal-policy --policy-source-arn "$PRINCIPAL" \
  --action-names ec2:RunInstances ec2:CreateKeyPair ec2:CreateSecurityGroup \
    ec2:AuthorizeSecurityGroupIngress ec2:TerminateInstances iam:PassRole \
    ssm:StartSession iam:CreateRole iam:AttachUserPolicy \
  --context-entries ContextKeyName=aws:RequestTag/managed_by,ContextKeyValues=claude-code,ContextKeyType=string \
  --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output text
```

Without `--resource-arns` the simulator evaluates every action against resource `*`, which allows scoped to specific ARNs never match. Under the agent role that means the EC2, SSM and PassRole actions all show `implicitDeny` in the call above. Re-check those one action at a time with a concrete ARN and the context the policy conditions on:

```
aws iam simulate-principal-policy --policy-source-arn "$PRINCIPAL" \
  --action-names ec2:RunInstances --resource-arns arn:aws:ec2:<REGION>:<ACCT>:instance/i-example \
  --context-entries ContextKeyName=aws:RequestTag/managed_by,ContextKeyValues=claude-code,ContextKeyType=string \
                    ContextKeyName=ec2:MetadataHttpTokens,ContextKeyValues=required,ContextKeyType=string \
  --query 'EvaluationResults[0].EvalDecision' --output text
```

For `ssm:StartSession` use the instance ARN with `ssm:resourceTag/managed_by`; for `iam:PassRole` use the worker role ARN with `iam:PassedToService=ec2.amazonaws.com`. Only an `explicitDeny`, or an `implicitDeny` on these concrete checks, means the caller really can't.

**Pick the connection model from the results:**

| The caller can | Connection |
|---|---|
| `ssm:StartSession` | **SSH over SSM** (default): fresh key pair, security group with **no inbound rules**, instance role gets `AmazonSSMManagedInstanceCore`. `scp` works; nothing is exposed. |
| `ec2:AuthorizeSecurityGroupIngress` but not `ssm:StartSession` | **SSH from the user's IP**: port 22 from `<USER_IP>/32` only. |
| neither | Stop. Draft the missing grant for the user (see "Granting the caller a permission" below). |

Needs the local `session-manager-plugin` for the SSM route (`which session-manager-plugin`).

**Network, image and IP** (in parallel):

```
aws configure list
aws ec2 describe-vpcs --filters Name=isDefault,Values=true \
  --query 'Vpcs[0].{VpcId:VpcId, CidrBlock:CidrBlock}'
# List every subnet with its public-IP flag and pick one that is True; filtering on the
# flag inside --query has returned nothing on some CLI builds.
aws ec2 describe-subnets --filters Name=vpc-id,Values=<VPC_ID> \
  --query 'Subnets[].[SubnetId,AvailabilityZone,MapPublicIpOnLaunch]' --output text

# Latest Amazon Linux 2023 x86_64 AMI in this region
# (SSM public params are the canonical source, but require ssm:GetParameter — use
# describe-images as a fallback that only needs ec2:DescribeImages.)
aws ec2 describe-images --owners amazon \
  --filters "Name=name,Values=al2023-ami-2023.*-kernel-*-x86_64" \
            "Name=state,Values=available" "Name=architecture,Values=x86_64" \
  --query 'sort_by(Images, &CreationDate)[-1].{ImageId:ImageId, Name:Name}'

# Current public IP (SSH-from-IP route only)
curl -sS https://checkip.amazonaws.com
```

Record the answers. They feed the launch command.

### Step 2 — Choose the instance role (read-only; create nothing yet)

Decision tree, in order; stop at the first that fits. This step only *decides*.

**A. Reuse a worker role the user already made for agent use.** Roles under the `/claude-workers/` path are the ones a `claude-agent` role may pass to EC2. List them with `aws iam list-roles --path-prefix /claude-workers/ --query 'Roles[].RoleName'` and check each one's policies cover the work.

**B. Draft a new scoped role for the user to create.** Write `trust.json` (`Service: ec2.amazonaws.com`) and `access.json` (only the actions and resources the work needs) to the scratchpad, plus `AmazonSSMManagedInstanceCore` for the SSM route. Put the role and its instance profile under the `/claude-workers/` path so an agent role can pass it. The user runs the creation commands in Step 3a.

**C. Reuse an existing broader role.** Survey what exists:
```
aws iam list-roles --query 'Roles[*].RoleName' --output text
# For each candidate name:
aws iam get-role --role-name <NAME> --query 'Role.AssumeRolePolicyDocument'
aws iam list-attached-role-policies --role-name <NAME>
aws iam list-role-policies --role-name <NAME>
```
The candidate must (1) trust `ec2.amazonaws.com` and (2) have the actions you need. If `iam:GetInstanceProfile` is denied, check what existing instances use:
```
aws ec2 describe-instances \
  --query 'Reservations[*].Instances[?IamInstanceProfile != null].IamInstanceProfile.Arn' \
  --output text | tr '\t' '\n' | sort -u
```
Trade-offs to surface: the blast radius widens (the role's permissions reach anything else using it), and the SSM route needs `AmazonSSMManagedInstanceCore` on it.

**Always present the trade-offs to the user before picking an option that compromises least-privilege.**

#### Granting the caller a permission

When Step 1 shows the caller lacks something (most often `ssm:StartSession`), draft a minimal policy file in the scratchpad, scoped by tag where the action supports it, and hand the user the commands. IAM's per-user limits bite here:

- A user's inline policies share **one 2,048-character budget** (whitespace not counted), so `put-user-policy` fails with `LimitExceeded` on a user who already has a few.
- A user can have at most **10 attached managed policies** by default.
- **Groups count toward neither.** When either limit is near, put the grant on a group:

```
! aws iam create-group --group-name <proj>-workers
! aws iam put-group-policy --group-name <proj>-workers --policy-name <grant> --policy-document file://<scratchpad>/<grant>.json
! aws iam add-user-to-group --group-name <proj>-workers --user-name <user>
```

Teardown is deleting the group. Don't consolidate or edit the user's existing policies to make room; those may be managed elsewhere (Terraform, shared with other users).

### Step 2b — Confirm the launch plan with the user (always, before any create call)

**Nothing is created — no IAM role, instance profile, key pair, security group or instance —
until the user has confirmed this plan in this session.** Present it in one message:

- Region, AZ/subnet, AMI, instance type, and the rough cost (see the cost note below).
- The identity Claude is running as (Step 1) and the connection model it supports.
- The instance role from Step 2. For B, the exact trust and access JSON and the role /
  instance-profile names; for A or C, the existing role and its trade-offs.
- For SSH from IP, the security-group CIDR (`<USER_IP>/32`).
- The full tag set as key=value pairs: the account's standard cost-allocation keys plus `Name`,
  `auto-terminate` and `managed_by=claude-code`. When a skill or doc in reach defines the
  account's tagging standard, take the keys and values from it rather than guessing; never
  invent a project or owner value.
- The teardown sequence you will hand back (Cleanup below), marking which commands the user runs.

Wait for the user to confirm or correct it. Do this even when the values seem obvious from the
repo or a previous run: a tag value is a permanent column in every future cost report, and an
IAM role outlives the instance unless someone deletes it. The same confirmed tag set goes on
every resource: role, instance profile, key pair, security group, instance, volume and ENI.

### Step 3 — Provision

Naming convention: prefix everything with the project name (`<proj>-ec2`, `<proj>-worker`,
`<proj>-worker-role`, `Name=<proj>-worker`). The confirmed tag set from Step 2b is written once
as shell variables and reused, so every resource carries every key.

```
T_PROJ=<project_name>; T_APP=<application_name>; T_COMP=<component>
T_OWNER=<owner>; T_FUND=<funding_source>
TAGS="{Key=project_name,Value=$T_PROJ},{Key=application_name,Value=$T_APP},{Key=component,Value=$T_COMP},{Key=owner,Value=$T_OWNER},{Key=funding_source,Value=$T_FUND},{Key=auto-terminate,Value=true},{Key=managed_by,Value=claude-code}"
```

#### 3a — Instance role (option B): the user runs these

Fill in the values and hand the block to the user, each line prefixed with `!` so it runs in the
session and its output lands in the conversation. EC2 attaches a role only through an instance
profile, and a new profile can take ~10 s to be usable.

```
! aws iam create-role --path /claude-workers/ --role-name <proj>-worker-role --assume-role-policy-document file://<scratchpad>/trust.json --tags Key=project_name,Value=<project_name> Key=application_name,Value=<application_name> Key=component,Value=<component> Key=owner,Value=<owner> Key=funding_source,Value=<funding_source> Key=auto-terminate,Value=true Key=managed_by,Value=claude-code
! aws iam put-role-policy --role-name <proj>-worker-role --policy-name <proj>-worker-access --policy-document file://<scratchpad>/access.json
! aws iam attach-role-policy --role-name <proj>-worker-role --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
! aws iam create-instance-profile --path /claude-workers/ --instance-profile-name <proj>-worker-profile --tags <same tags>
! aws iam add-role-to-instance-profile --instance-profile-name <proj>-worker-profile --role-name <proj>-worker-role
! aws iam wait instance-profile-exists --instance-profile-name <proj>-worker-profile
```

Drop the `attach-role-policy` line for the SSH-from-IP route.

#### 3b — Key pair, security group, instance: Claude runs these

```
# Key pair (both routes). ED25519 over RSA. AWS returns the private key ONCE — save it, chmod 600.
KEY_PATH="$HOME/.ssh/<proj>-ec2.pem"
[ -f "$KEY_PATH" ] && { echo "KEY EXISTS — refusing to overwrite"; exit 1; }
aws ec2 create-key-pair --key-name <proj>-ec2 --key-type ed25519 \
  --tag-specifications "ResourceType=key-pair,Tags=[$TAGS]" \
  --query KeyMaterial --output text > "$KEY_PATH"
chmod 600 "$KEY_PATH"

# Security group. SSH over SSM: create it and add no ingress rule at all.
SG_ID=$(aws ec2 create-security-group \
  --vpc-id <VPC_ID> \
  --group-name <proj>-worker \
  --description "<purpose, owner>" \
  --tag-specifications "ResourceType=security-group,Tags=[$TAGS]" \
  --query GroupId --output text)
# SSH-from-IP route only: port 22 from the user's current IP. Never 0.0.0.0/0.
aws ec2 authorize-security-group-ingress --group-id "$SG_ID" \
  --protocol tcp --port 22 --cidr <USER_IP>/32

# Launch. Instance-profile auth (NOT --user-data with keys), IMDSv2 only,
# shutdown=terminate so `sudo shutdown -h now` from inside cleans up the box.
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

aws ec2 wait instance-running --instance-ids <INSTANCE_ID>
```

Notes on the launch flags:
- `t3.micro` is the right default for I/O-bound CLI work like `aws s3 cp`. Size up for real compute (DuckDB, GDAL, large sorts): memory first.
- Default 8 GB gp3 EBS is fine unless the work writes large local files (S3-to-S3 copy doesn't touch local disk). For bigger disks pass `--block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=<GB>,VolumeType=gp3,DeleteOnTermination=true,Encrypted=true}'`.
- Don't set a public IP explicitly; the public-IP-assigning subnet from Step 1 handles it. The SSM route still needs outbound internet (or VPC endpoints) for the agent to reach SSM.

### Step 4 — Connect and verify

**SSH over SSM** (instance ID as the host; no open port):
```
ssh -i ~/.ssh/<proj>-ec2.pem \
  -o ProxyCommand="aws ssm start-session --region <REGION> --target %h --document-name AWS-StartSSHSession --parameters portNumber=%p" \
  ec2-user@<INSTANCE_ID>
```
The SSM agent can take a few minutes to register on first boot. Retry the connection every 15 s for up to ~5 minutes rather than polling `ssm:DescribeInstanceInformation`, which the caller may not have. Run the retry loop in the background or under Monitor; a long foreground `sleep` loop hits the tool timeout.

**SSH from IP:** `ssh -i ~/.ssh/<proj>-ec2.pem ec2-user@<PUBLIC_IP>`; the first attempt may fail while cloud-init runs, so retry every 15 s for ~90 s.

Don't declare done until the instance proves it can do the job:
```
# Confirms the instance role is assumed, not user keys
aws sts get-caller-identity
# Confirms tooling
aws --version && python3 --version
# Confirms access to the actual resources you provisioned for
aws s3 ls s3://<bucket-the-instance-is-meant-to-touch>/ | head
```

If `get-caller-identity` returns a user ARN instead of `assumed-role/.../i-...`, the instance profile didn't attach correctly — investigate before proceeding.

### Step 5 — Track resources for cleanup

Save the resource IDs immediately, to a project memory file (preferred when running in Claude Code with memory) or a scratch file outside the repo. Don't commit them: public IPs, key paths and instance IDs don't belong in git history. Capture:

- Instance ID, region, AZ, subnet, VPC, AMI, instance type, volume ID
- Public IP and DNS (ephemeral if the instance is stopped/started)
- Key pair name + local .pem path
- Security group ID + the CIDR it allows (or "no ingress")
- Instance role / profile, and whether the user created it for this run (B) or it was reused
- Any grant the user applied for the caller (e.g. a `<proj>-workers` group)
- Reconnect command
- The exact teardown sequence (below)

### Cleanup pattern (run when done)

Order matters: the SG can't be deleted while attached to a running instance, and a role can't be deleted while it's in an instance profile or still has policies.

Claude runs the EC2 part:
```
aws ec2 terminate-instances --instance-ids <INSTANCE_ID>
aws ec2 wait instance-terminated --instance-ids <INSTANCE_ID>
aws ec2 delete-security-group --group-id <SG_ID>
aws ec2 delete-key-pair --key-name <proj>-ec2
rm ~/.ssh/<proj>-ec2.pem
```

The user runs the IAM part, and only for a role created for this run (option B) — never delete a reused role:
```
! aws iam remove-role-from-instance-profile --instance-profile-name <proj>-worker-profile --role-name <proj>-worker-role
! aws iam delete-instance-profile --instance-profile-name <proj>-worker-profile
! aws iam delete-role-policy --role-name <proj>-worker-role --policy-name <proj>-worker-access
! aws iam detach-role-policy --role-name <proj>-worker-role --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
! aws iam delete-role --role-name <proj>-worker-role
```
plus removing any caller grant made for the run (`delete-group-policy`, `remove-user-from-group`, `delete-group`) once no further workers are planned.

Cost note for the user: a running t3.micro is roughly USD 0.0104/hr (about USD 0.25/day) outside Free Tier. Stopped instances incur no compute cost but EBS volumes still bill (about USD 0.08/GB-month for gp3, roughly USD 0.02/day for 8 GB). For one-shot work, terminate, don't stop. Look up other instance types with `aws pricing get-products --region us-east-1 --service-code AmazonEC2` filtered on `instanceType` and `regionCode`. Write prices as "USD n", never a dollar sign before a digit: skill arguments are substituted into `$`-digit sequences.

## Safety guardrails — non-negotiable defaults

These are not opinions. Don't skip them without explicit user opt-out:

1. **Same region as the data.** EC2 in us-east-1 doing `aws s3 cp` to a us-west-2 bucket transfers across regions and defeats the purpose.
2. **`--metadata-options HttpTokens=required`** — IMDSv2 only. Closes a known SSRF class.
3. **`--instance-initiated-shutdown-behavior terminate`** for ad-hoc workers. Makes "I'm done" a one-command action.
4. **No inbound rules on the SSM route; SSH from the user's current IP only otherwise.** Never `0.0.0.0/0`.
5. **Instance-profile auth**, never `aws configure` with the user's access keys on the box. Long-lived creds on shared compute is the antipattern that instance profiles exist to fix.
6. **Fresh project key pair**, not the user's general SSH identity. Scoped to the project, deletable at cleanup.
7. **Tag everything** with the confirmed tag set plus `auto-terminate=true` and `managed_by=claude-code` — on the instance, its volume, its ENI, and every other resource you create. Untagged AWS resources are how cloud bills compound forever. When a skill or doc defines the account's tagging standard, follow it rather than restating it here.
8. **Confirm before creating anything**, IAM included (Step 2b), and hand back a teardown that removes everything created.
9. **IAM writes are drafted, not run.** Claude writes the policy files and the commands; the user applies them. Claude never grants its own identity a permission, whatever its credentials allow.
10. **Check the connection permission before launching** (Step 1), so a no-ingress worker is never stranded without a way in.

## When this skill is the wrong tool

- The work is short and laptop-friendly (e.g., a one-time CLI call that finishes in under a minute). Don't EC2 a curl.
- The user already has bastion/jumphost infrastructure. Use that instead of provisioning new boxes.
- The work needs persistent state, scaling, scheduling, or a network address that doesn't change. That's an ECS/Fargate/Lambda/EC2 ASG conversation, not an ad-hoc worker.
- The user is unfamiliar with AWS billing. Surface the cost and cleanup path explicitly before launching anything.
