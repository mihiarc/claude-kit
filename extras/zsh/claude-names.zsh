# Claude Code: start each interactive session with a stable name, which other
# sessions use as its messaging address: <repo> in a main checkout,
# <repo>--<task> for `--worktree <task>` or inside a linked worktree, and the
# folder's name outside a repo. An explicit --name, a resume or continue,
# print mode, a subcommand, or a run without a terminal passes through as is.
claude() {
  if [[ ! -t 0 || ! -t 1 ]] ||
     (( ${@[(I)(-n|--name|--name=*|-r|--resume|--resume=*|-c|--continue|-p|--print|-h|--help|-v|--version)]} )); then
    command claude "$@"; return
  fi
  case $1 in
    agents|attach|auth|auto-mode|doctor|gateway|import|install|logs|mcp|plugin|purge|respawn|rm|setup-token|stop|ultrareview|update)
      command claude "$@"; return ;;
  esac

  local name=${PWD:t} common top task i
  if common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null); then
    name=${common:h:t}
    top=$(git rev-parse --show-toplevel 2>/dev/null)
    [[ -n $top && $top != ${common:h} ]] && task=${top:t}
  fi

  i=${@[(I)(-w|--worktree)]}
  if (( i )); then
    task=${@[i+1]}
    # A bare -w lets Claude Code pick a random worktree name; leave that session unnamed.
    [[ -z $task || $task == -* ]] && { command claude "$@"; return; }
  fi
  i=${@[(I)--worktree=*]}
  (( i )) && task=${@[i]#--worktree=}

  command claude --name "${name}${task:+--$task}" "$@"
}
