# claude-kit shell setup for bash. install.sh sources it from ~/.bashrc.

# `claude` names each interactive session after its repo, or <repo>--<task> in a worktree.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/claude-names.bash"

# `kit-secret` sets secrets without anyone pasting them into a chat (extras/secrets).
_kit_secrets="$(cd "$(dirname "${BASH_SOURCE[0]}")/../secrets" && pwd -P)"
case ":$PATH:" in *":$_kit_secrets:"*) ;; *) PATH="$PATH:$_kit_secrets" ;; esac
unset _kit_secrets
