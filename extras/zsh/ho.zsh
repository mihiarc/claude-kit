# ho: start the Claude Code session a handoff prompt describes, and continue into a queued one
# when a session exits. Source this from ~/.zshrc. Details: `ho --help`, or
# plugins/handoff/skills/handoff/scripts/ho.py.

_HO_PY=${${(%):-%x}:A:h:h:h}/plugins/handoff/skills/handoff/scripts/ho.py
export HO_SHELL_HOOK=1   # tells ho a session started from this shell can continue in it

ho() {
  local a
  for a in "$@"; do
    case $a in
      --window|--bg|--next|--relaunch|--detach|--runs|--dry-run|-h|--help) python3 "$_HO_PY" "$@"; return ;;
    esac
  done
  local cmd
  cmd=$(python3 "$_HO_PY" "$@") || return
  [[ -n $cmd ]] && eval "$cmd"
}

# When a session queued a handoff for this shell (`ho --next`, or the coordinator's
# `ho --relaunch`), start it as soon as the old session returns to the prompt.
_ho_pending() {
  local cmd
  while [[ -e ${HO_HANDOFFS:-$HOME/.claude/handoffs}/.next/shell-$$ ]]; do
    cmd=$(python3 "$_HO_PY" --pending $$) || return
    [[ -n $cmd ]] || return
    eval "$cmd"
  done
}
autoload -Uz add-zsh-hook && add-zsh-hook precmd _ho_pending
