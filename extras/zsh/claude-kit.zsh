# claude-kit shell setup for zsh. install.sh sources it from ~/.zshrc.

# Claude Code's Bash tool runs commands through your shell; inside Claude Code (CLAUDECODE is
# set only there) parse them as bash would, and let `log` reach the macOS command.
if [[ -n $CLAUDECODE ]]; then setopt sh_word_split no_nomatch no_equals; disable log 2>/dev/null; fi

# `claude` names each interactive session after its repo, or <repo>--<task> in a worktree.
source "${${(%):-%x}:A:h}/claude-names.zsh"

# `kit-secret` sets secrets without anyone pasting them into a chat (extras/secrets).
typeset -gU path; path+=("${${(%):-%x}:A:h:h}/secrets")
