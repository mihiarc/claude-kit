# Claude Code: start each interactive session with a stable name, which other
# sessions use as its messaging address: <repo> in a main checkout,
# <repo>--<task> for `--worktree <task>` or inside a linked worktree, and the
# folder's name outside a repo. An explicit --name, a resume or continue,
# print mode, a subcommand, or a run without a terminal passes through as is.
# The bash version of extras/zsh/claude-names.zsh; it runs on bash 3.2.
claude() {
  local a
  if [[ ! -t 0 || ! -t 1 ]]; then command claude "$@"; return; fi
  for a in "$@"; do
    case $a in
      -n|--name|--name=*|-r|--resume|--resume=*|-c|--continue|-p|--print|-h|--help|-v|--version)
        command claude "$@"; return ;;
    esac
  done
  case ${1-} in
    agents|attach|auth|auto-mode|doctor|gateway|import|install|logs|mcp|plugin|purge|respawn|rm|setup-token|stop|ultrareview|update)
      command claude "$@"; return ;;
  esac

  local name=${PWD##*/} common top root task='' i w=-1 eq='' haveeq=0
  local -a args=("$@")
  if common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null); then
    root=$(dirname "$common")
    name=${root##*/}
    top=$(git rev-parse --show-toplevel 2>/dev/null)
    [[ -n $top && $top != "$root" ]] && task=${top##*/}
  fi

  for (( i = 0; i < ${#args[@]}; i++ )); do
    case ${args[i]} in
      -w|--worktree) w=$i ;;
      --worktree=*) eq=${args[i]#--worktree=}; haveeq=1 ;;
    esac
  done
  if (( w >= 0 )); then
    task=${args[w+1]-}
    # A bare -w lets Claude Code pick a random worktree name; leave that session unnamed.
    [[ -z $task || $task == -* ]] && { command claude "$@"; return; }
  fi
  (( haveeq )) && task=$eq

  command claude --name "${name}${task:+--$task}" "$@"
}
