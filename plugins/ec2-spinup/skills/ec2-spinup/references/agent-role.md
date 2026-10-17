# A scoped AWS identity for Claude: the `claude-agent` role

By default Claude Code runs `aws` with whatever credentials the user's shell has. If those can
write IAM, nothing in AWS stops the agent from widening its own access; permission rules in
Claude Code match command text and are not a security boundary (`bash -c`, a boto3 script, or a
full path to `aws` slip past them). The boundary has to be IAM itself.

This setup gives Claude its own role, hands Claude only that role's short-lived credentials, and
hides the user's own keys from Claude's shell. The user runs every command here; Claude drafts.

| Layer | What it does | Enforced by |
|---|---|---|
| `claude-agent` role | Claude can launch, connect to and terminate only resources tagged `managed_by=claude-code`, read the buckets listed for it, and view (not read) everything else. No IAM writes, no assuming other roles. | AWS IAM |
| Permissions boundary | Keeps the IAM denies in force even if someone later attaches a broader policy to the role. | AWS IAM |
| `claude-aws` wrapper | Starts Claude Code with the role's temporary credentials (up to 12 h) and a session name per folder, so CloudTrail separates agent actions from the user's. | the shell |
| Sandbox credential deny | Stops Claude's commands reading `~/.aws`, so the user's own key can't be picked up instead. Without it the role is advisory. | the OS sandbox |
| Deny rules / auto-mode | Catch honest mistakes early. | Claude Code (convenience only) |

Placeholders: `<ACCT>` account ID, `<REGION>` region, `<USER>` the human's IAM user name,
`<BUCKET>` each bucket Claude may read and write (repeat the ARN for several).

## 1. Policies

**Trust** (`claude-agent-trust.json`). Same-account trust that names the user's ARN is enough for
that user to assume the role; if `assume-role` is still denied, add `sts:AssumeRole` on the role
ARN to the user through a group. Add `"Condition": {"Bool": {"aws:MultiFactorAuthPresent": "true"}}`
to require MFA (the wrapper then needs `--serial-number` and `--token-code`).

```json
{"Version": "2012-10-17", "Statement": [{
  "Effect": "Allow",
  "Principal": {"AWS": "arn:aws:iam::<ACCT>:user/<USER>"},
  "Action": "sts:AssumeRole"}]}
```

**Access** (`claude-agent-access.json`, a customer-managed policy). The role also gets the AWS
managed `job-function/ViewOnlyAccess`, which covers `Describe*`/`List*` (including bucket and key
listings) but no object reads.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Sid": "ReadIamAndSimulate", "Effect": "Allow",
     "Action": ["iam:GetRole", "iam:GetInstanceProfile", "iam:GetRolePolicy", "iam:ListRoles",
                "iam:ListInstanceProfiles", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies",
                "iam:SimulatePrincipalPolicy"],
     "Resource": "*"},
    {"Sid": "PassWorkerRoles", "Effect": "Allow", "Action": "iam:PassRole",
     "Resource": "arn:aws:iam::<ACCT>:role/claude-workers/*",
     "Condition": {"StringEquals": {"iam:PassedToService": "ec2.amazonaws.com"}}},

    {"Sid": "LaunchTaggedInstancesAndVolumes", "Effect": "Allow", "Action": "ec2:RunInstances",
     "Resource": ["arn:aws:ec2:<REGION>:<ACCT>:instance/*", "arn:aws:ec2:<REGION>:<ACCT>:volume/*"],
     "Condition": {"StringEquals": {"aws:RequestTag/managed_by": "claude-code"}}},
    {"Sid": "LaunchSupportingResources", "Effect": "Allow", "Action": "ec2:RunInstances",
     "Resource": ["arn:aws:ec2:<REGION>::image/*", "arn:aws:ec2:<REGION>:<ACCT>:subnet/*",
                  "arn:aws:ec2:<REGION>:<ACCT>:security-group/*", "arn:aws:ec2:<REGION>:<ACCT>:key-pair/*",
                  "arn:aws:ec2:<REGION>:<ACCT>:network-interface/*"]},
    {"Sid": "TagOnlyAtCreate", "Effect": "Allow", "Action": "ec2:CreateTags",
     "Resource": "arn:aws:ec2:<REGION>:<ACCT>:*/*",
     "Condition": {"StringEquals": {"ec2:CreateAction": ["RunInstances", "CreateSecurityGroup", "CreateKeyPair"]}}},
    {"Sid": "CreateTaggedSecurityGroupsAndKeys", "Effect": "Allow",
     "Action": ["ec2:CreateSecurityGroup", "ec2:CreateKeyPair"],
     "Resource": ["arn:aws:ec2:<REGION>:<ACCT>:security-group/*", "arn:aws:ec2:<REGION>:<ACCT>:key-pair/*"],
     "Condition": {"StringEquals": {"aws:RequestTag/managed_by": "claude-code"}}},
    {"Sid": "SecurityGroupsLiveInAVpc", "Effect": "Allow", "Action": "ec2:CreateSecurityGroup",
     "Resource": "arn:aws:ec2:<REGION>:<ACCT>:vpc/*"},

    {"Sid": "ManageOwnInstances", "Effect": "Allow",
     "Action": ["ec2:StartInstances", "ec2:StopInstances", "ec2:RebootInstances", "ec2:TerminateInstances"],
     "Resource": "arn:aws:ec2:<REGION>:<ACCT>:instance/*",
     "Condition": {"StringEquals": {"aws:ResourceTag/managed_by": "claude-code"}}},
    {"Sid": "ManageOwnSecurityGroupsAndKeys", "Effect": "Allow",
     "Action": ["ec2:AuthorizeSecurityGroupIngress", "ec2:RevokeSecurityGroupIngress",
                "ec2:DeleteSecurityGroup", "ec2:DeleteKeyPair"],
     "Resource": ["arn:aws:ec2:<REGION>:<ACCT>:security-group/*", "arn:aws:ec2:<REGION>:<ACCT>:key-pair/*"],
     "Condition": {"StringEquals": {"aws:ResourceTag/managed_by": "claude-code"}}},
    {"Sid": "IngressRuleObjects", "Effect": "Allow", "Action": "ec2:AuthorizeSecurityGroupIngress",
     "Resource": "arn:aws:ec2:<REGION>:<ACCT>:security-group-rule/*"},

    {"Sid": "SshOverSsmToOwnInstances", "Effect": "Allow", "Action": "ssm:StartSession",
     "Resource": "arn:aws:ec2:<REGION>:<ACCT>:instance/*",
     "Condition": {"StringEquals": {"ssm:resourceTag/managed_by": "claude-code"}}},
    {"Sid": "SshSessionDocument", "Effect": "Allow", "Action": "ssm:StartSession",
     "Resource": "arn:aws:ssm:*:*:document/AWS-StartSSHSession"},
    {"Sid": "OwnSessions", "Effect": "Allow",
     "Action": ["ssm:TerminateSession", "ssm:ResumeSession", "ssmmessages:OpenDataChannel"],
     "Resource": ["arn:aws:ssm:*:*:session/${aws:userid}-*", "arn:aws:ssm:*:*:session/claude-*"]},

    {"Sid": "PriceLookups", "Effect": "Allow", "Action": "pricing:GetProducts", "Resource": "*"},
    {"Sid": "ProjectBucketObjects", "Effect": "Allow",
     "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"],
     "Resource": ["arn:aws:s3:::<BUCKET>/*"]},
    {"Sid": "ProjectBucketListing", "Effect": "Allow",
     "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
     "Resource": ["arn:aws:s3:::<BUCKET>"]},

    {"Sid": "RequireImdsV2", "Effect": "Deny", "Action": "ec2:RunInstances",
     "Resource": "arn:aws:ec2:*:*:instance/*",
     "Condition": {"StringNotEquals": {"ec2:MetadataHttpTokens": "required"}}},
    {"Sid": "NoIamWritesNoRoleHopping", "Effect": "Deny",
     "Action": ["iam:Add*", "iam:Attach*", "iam:Change*", "iam:Create*", "iam:Deactivate*",
                "iam:Delete*", "iam:Detach*", "iam:Enable*", "iam:Put*", "iam:Remove*", "iam:Reset*",
                "iam:Set*", "iam:Tag*", "iam:Untag*", "iam:Update*", "iam:Upload*",
                "sts:AssumeRole", "sts:AssumeRoleWithSAML", "sts:AssumeRoleWithWebIdentity",
                "organizations:*", "account:*"],
     "Resource": "*"}
  ]
}
```

Notes on the less obvious statements:

- `RunInstances` checks several resources at once. Instances and volumes must carry the tag in the
  request; images, subnets, security groups, key pairs and network interfaces are allowed
  unconditioned (AWS's own example does the same).
- `TagOnlyAtCreate` means tags can be set only as part of creating the resource, so the agent can't
  put `managed_by=claude-code` on something it didn't create and then terminate it.
- Session Manager session IDs are matched both ways (`${aws:userid}-*` from AWS's samples, and the
  `claude-` role session name the wrapper sets). If ending a session is ever denied, closing SSH
  still ends it.
- `PassRole` is checked against the role ARN (path included), not the instance profile, so worker
  roles go under the `/claude-workers/` path.
- `iam:PassRole`, `Get*`, `List*` and `SimulatePrincipalPolicy` don't match any denied prefix, so
  reading IAM and passing worker roles still work.

**Boundary** (`claude-agent-boundary.json`). Allows everything, then repeats the two Deny
statements above verbatim. The role's effective permissions are the intersection of the boundary
and its policies, and an explicit Deny in either wins. The boundary can't be removed by the role,
because `iam:Delete*` and `iam:Put*` cover `DeleteRolePermissionsBoundary` and
`PutRolePermissionsBoundary`.

```json
{"Version": "2012-10-17", "Statement": [
  {"Sid": "Ceiling", "Effect": "Allow", "Action": "*", "Resource": "*"},
  <the RequireImdsV2 and NoIamWritesNoRoleHopping statements from the access policy>
]}
```

## 2. Create it (the user runs these)

```
! aws iam create-policy --policy-name claude-agent-boundary --policy-document file://claude-agent-boundary.json
! aws iam create-policy --policy-name claude-agent-access --policy-document file://claude-agent-access.json
! aws iam create-role --role-name claude-agent --max-session-duration 43200 --assume-role-policy-document file://claude-agent-trust.json --permissions-boundary arn:aws:iam::<ACCT>:policy/claude-agent-boundary
! aws iam attach-role-policy --role-name claude-agent --policy-arn arn:aws:iam::<ACCT>:policy/claude-agent-access
! aws iam attach-role-policy --role-name claude-agent --policy-arn arn:aws:iam::aws:policy/job-function/ViewOnlyAccess
```

Adding a bucket later is a new policy version (`aws iam create-policy-version --set-as-default`;
IAM keeps five).

Resources made before this setup lack the tag, so the agent can't stop or terminate them. Tag
them by hand if the agent should manage them:
`aws ec2 create-tags --resources <ids> --tags Key=managed_by,Value=claude-code`.

## 3. Start Claude with the role's credentials

`extras/zsh/claude-aws.zsh` in this kit defines `claude-aws`. Source it after the `claude`
function and set the role ARN:

```zsh
export CLAUDE_AGENT_ROLE_ARN=arn:aws:iam::<ACCT>:role/claude-agent
export CLAUDE_AGENT_REGION=<REGION>
source ~/Github/mihiarc/claude-kit/extras/zsh/claude-aws.zsh
```

Then `claude-aws` in place of `claude`. It assumes the role with the user's own credentials,
names the session `claude-<folder>`, and starts Claude Code with only the temporary credentials
in its environment. The credentials expire after 12 hours; restart with `claude-aws --continue`.

If the user moves their own login to IAM Identity Center, assuming `claude-agent` from an SSO
session is role chaining, which AWS caps at one hour. Give the agent its own permission set
instead and have the wrapper use that profile.

## 4. Hide the user's keys from Claude's shell

Without this, Claude could run `aws --profile default …` or read `~/.aws/credentials` directly.
In the **user** settings (`~/.claude/settings.json`; project settings are ignored for this):

```json
"sandbox": {
  "enabled": true,
  "allowUnsandboxedCommands": false,
  "credentials": {"files": [
    {"path": "~/.aws/credentials", "mode": "deny"},
    {"path": "~/.aws/config", "mode": "deny"},
    {"path": "~/.aws/sso/cache", "mode": "deny"},
    {"path": "~/.aws/cli/cache", "mode": "deny"}]},
  "network": {"allowedDomains": ["*.amazonaws.com", "pypi.org", "files.pythonhosted.org",
                                 "github.com", "*.githubusercontent.com"]}
}
```

The sandbox applies to every session, so its network allowlist must cover everything Claude
reaches from the shell (package indexes, git hosts, APIs). Check the key names against the
current Claude Code settings reference, and try it in one session before relying on it.
`~/.aws/config` is denied too, which is why the wrapper sets the region in the environment.

Optional guards in the same file. They match command text only, so they catch mistakes, not
intent:

```json
"permissions": {"deny": [
  "Bash(aws iam create-*)", "Bash(aws iam put-*)", "Bash(aws iam attach-*)", "Bash(aws iam detach-*)",
  "Bash(aws iam delete-*)", "Bash(aws iam update-*)", "Bash(aws iam add-*)", "Bash(aws iam remove-*)",
  "Bash(aws sts assume-role*)", "Bash(aws organizations *)"]}
```

## 5. Verify

In a session started with `claude-aws`:

1. `aws sts get-caller-identity` shows `assumed-role/claude-agent/claude-<folder>`.
2. `aws iam simulate-principal-policy --policy-source-arn arn:aws:iam::<ACCT>:role/claude-agent --action-names iam:CreateRole iam:AttachRolePolicy sts:AssumeRole` shows `explicitDeny` for all three.
3. The same call for `ec2:RunInstances` with `--context-entries ContextKeyName=aws:RequestTag/managed_by,ContextKeyValues=claude-code,ContextKeyType=string` shows `allowed`.
4. `cat ~/.aws/credentials` fails inside the sandbox.
5. One small worker through this skill, launch to teardown.

## 6. Afterwards: the user's own permissions

Once Claude runs as `claude-agent`, grants that were added to the user's identity so an agent
could do a specific job can move to the agent role (if recurring) or be deleted (if finished).
IAM's last-accessed report (`aws iam generate-service-last-accessed-details`) shows which ones
haven't been used. Keep broad IAM rights behind a separate admin role that requires MFA, rather
than on the everyday key.

## Removing it

```
! aws iam detach-role-policy --role-name claude-agent --policy-arn arn:aws:iam::<ACCT>:policy/claude-agent-access
! aws iam detach-role-policy --role-name claude-agent --policy-arn arn:aws:iam::aws:policy/job-function/ViewOnlyAccess
! aws iam delete-role --role-name claude-agent
! aws iam delete-policy --policy-arn arn:aws:iam::<ACCT>:policy/claude-agent-access
! aws iam delete-policy --policy-arn arn:aws:iam::<ACCT>:policy/claude-agent-boundary
```
