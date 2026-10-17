# claude-aws: start Claude Code with only the claude-agent role's temporary AWS credentials.
# Set CLAUDE_AGENT_ROLE_ARN (and CLAUDE_AGENT_REGION) before sourcing; see
# skills/ec2-spinup/references/agent-role.md. The role session is named after the current
# folder, so CloudTrail shows which session acted. Arguments pass through to `claude`.
claude-aws() {
  local role=${CLAUDE_AGENT_ROLE_ARN:?set CLAUDE_AGENT_ROLE_ARN to the claude-agent role ARN}
  local session="claude-${${PWD:t}//[^A-Za-z0-9+=,.@-]/-}"
  session=${session[1,64]}
  local creds ak sk st
  creds=$(command aws sts assume-role --role-arn "$role" --role-session-name "$session" \
    --duration-seconds "${CLAUDE_AGENT_DURATION:-43200}" \
    --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' --output text) || return
  read -r ak sk st <<< "$creds"
  (
    unset AWS_PROFILE AWS_DEFAULT_PROFILE
    export AWS_ACCESS_KEY_ID=$ak AWS_SECRET_ACCESS_KEY=$sk AWS_SESSION_TOKEN=$st
    export AWS_REGION=${CLAUDE_AGENT_REGION:-${AWS_REGION:-us-east-1}}
    claude "$@"
  )
}
