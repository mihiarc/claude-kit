#!/usr/bin/env bash
# Claude Code status line — identity, context-window usage, and rate limits.
#
# Reads the session JSON from stdin. Field reference:
#   https://code.claude.com/docs/en/statusline
#
# Line 1: session-name │ user:dir [git-branch] model effort
# Line 2: context tokens against the handoff budget | 5-hour and 7-day limits,
#         each with its projected use at reset
#
# Written in bash + jq (not Python/rich) on purpose: the status line re-runs
# after every assistant message, so it must stay fast — a Python+rich startup
# on each refresh would lag the UI. ANSI escape codes give us the color.

session_json=$(cat)

# --- Colors -----------------------------------------------------------------
color_cyan='\033[36m'
color_green='\033[32m'
color_yellow='\033[33m'
color_red='\033[31m'
color_magenta='\033[35m'
color_dim='\033[2m'
color_bold='\033[1m'
color_reset='\033[0m'

# The context bar fills toward a handoff budget, in tokens. Absolute because
# every turn re-reads the whole context, so cost tracks tokens, not the share
# of the model's window. Yellow: start looking for a stopping point. Red: hand off.
handoff_budget_tokens=400000
context_tokens_yellow=250000

# --- Parse every field we need in a single jq pass --------------------------
# Percentages are floored to integers so bash arithmetic works. Absent values
# become -1 (rate limits) or sensible fallbacks (context fields).
# Fields are joined with the ASCII unit separator: unlike tab, it isn't IFS
# whitespace, so an empty field stays in place instead of shifting the rest.
IFS=$'\x1f' read -r session_name model_display_name effort_level current_directory_name \
                 context_input_tokens \
                 five_hour_percent five_hour_reset_epoch \
                 seven_day_percent seven_day_reset_epoch \
                 session_id session_cost_usd < <(
  printf '%s' "$session_json" | jq -r '
    [ (.session_name // ""),
      (.model.display_name // "?"),
      (.effort.level // ""),
      (.workspace.current_dir // "" | split("/") | last // ""),
      (.context_window.total_input_tokens // 0),
      (.rate_limits.five_hour.used_percentage  // -1 | floor),
      (.rate_limits.five_hour.resets_at        // -1),
      (.rate_limits.seven_day.used_percentage  // -1 | floor),
      (.rate_limits.seven_day.resets_at        // -1),
      (.session_id // ""),
      (.cost.total_cost_usd // 0)
    ] | map(tostring) | join("\u001f")'
)

# --- Helpers ----------------------------------------------------------------

# Pick a traffic-light color from a 0-100 percentage.
percent_to_color() {
  local percent=$1
  if   (( percent >= 90 )); then printf '%b' "$color_red"
  elif (( percent >= 70 )); then printf '%b' "$color_yellow"
  else                           printf '%b' "$color_green"
  fi
}

# Pick a traffic-light color from a context size in tokens.
tokens_to_color() {
  local token_count=$1
  if   (( token_count >= handoff_budget_tokens )); then printf '%b' "$color_red"
  elif (( token_count >= context_tokens_yellow )); then printf '%b' "$color_yellow"
  else                                                  printf '%b' "$color_green"
  fi
}

# Humanize a token count: 1234 -> 1k, 1500000 -> 1.5M.
humanize_tokens() {
  local token_count=$1
  if   (( token_count >= 1000000 )); then
    printf '%d.%dM' $(( token_count / 1000000 )) $(( (token_count % 1000000) / 100000 ))
  elif (( token_count >= 1000 )); then
    printf '%dk' $(( token_count / 1000 ))
  else
    printf '%d' "$token_count"
  fi
}

# Turn a reset epoch into a "resets in 2h13m" countdown.
format_reset_countdown() {
  local reset_epoch=$1
  (( reset_epoch < 0 )) && return
  local now seconds_remaining
  now=$(date +%s)
  seconds_remaining=$(( reset_epoch - now ))
  (( seconds_remaining < 0 )) && seconds_remaining=0
  if   (( seconds_remaining >= 86400 )); then
    printf '%dd%dh' $(( seconds_remaining / 86400 )) $(( (seconds_remaining % 86400) / 3600 ))
  elif (( seconds_remaining >= 3600 )); then
    printf '%dh%dm' $(( seconds_remaining / 3600 )) $(( (seconds_remaining % 3600) / 60 ))
  else
    printf '%dm' $(( seconds_remaining / 60 ))
  fi
}

# Build one rate-limit segment, e.g. "7d 75%→112% (2d7h)": used so far, then
# where the current pace lands at reset. Color follows the projection, so red
# means on pace to spill into usage credits (the cue to drop effort). The
# projection waits until min_elapsed_seconds of the window have passed, since
# early extrapolations swing wildly. Empty if the window is absent (not a
# Pro/Max subscriber, or before the first API response).
build_limit_segment() {
  local label=$1 percent=$2 reset_epoch=$3 window_seconds=$4 min_elapsed_seconds=$5
  (( percent < 0 )) && return
  local reset_countdown usage_text segment_color elapsed_seconds projected_percent
  reset_countdown=$(format_reset_countdown "$reset_epoch")

  if (( percent >= 100 )); then
    usage_text="credits"
    segment_color=$color_red
  else
    usage_text="${percent}%"
    segment_color=$(percent_to_color "$percent")
    if (( reset_epoch >= 0 )); then
      elapsed_seconds=$(( window_seconds - (reset_epoch - $(date +%s)) ))
      if (( elapsed_seconds >= min_elapsed_seconds )); then
        projected_percent=$(( percent * window_seconds / elapsed_seconds ))
        usage_text="${percent}%→${projected_percent}%"
        if   (( projected_percent > 100 )); then segment_color=$color_red
        elif (( projected_percent >= 90 )); then segment_color=$color_yellow
        else                                     segment_color=$color_green
        fi
      fi
    fi
  fi

  printf '%b%s %s%b' "$segment_color" "$label" "$usage_text" "$color_reset"
  [ -n "$reset_countdown" ] && printf ' %b(%s)%b' "$color_dim" "$reset_countdown" "$color_reset"
}

# --- Line 1: identity -------------------------------------------------------
git_branch_part=""
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  current_git_branch=$(git branch --show-current 2>/dev/null)
  [ -n "$current_git_branch" ] && git_branch_part=" [${color_yellow}${current_git_branch}${color_reset}]"
fi

# Effort is absent when the model doesn't support the effort parameter.
effort_part=""
[ -n "$effort_level" ] && effort_part=" ${color_dim}${effort_level}${color_reset}"

# session_name is the --name / /rename name, which peers message; in an unnamed
# session it is the AI-generated title instead, and absent before one exists.
session_name_part=""
[ -n "$session_name" ] && session_name_part="${color_bold}${session_name}${color_reset} ${color_dim}│${color_reset} "

printf '%b%b%s%b:%b%s%b%b %b%s%b%b\n' \
  "$session_name_part" \
  "$color_cyan"    "$(whoami)"               "$color_reset" \
  "$color_green"   "$current_directory_name" "$color_reset" \
  "$git_branch_part" \
  "$color_magenta" "$model_display_name"     "$color_reset" \
  "$effort_part"

# --- Line 2: context window + limits ----------------------------------------
bar_width=10
filled_block_count=$(( context_input_tokens * bar_width / handoff_budget_tokens ))
(( filled_block_count > bar_width )) && filled_block_count=$bar_width
empty_block_count=$(( bar_width - filled_block_count ))

printf -v filled_run "%${filled_block_count}s" ""
printf -v empty_run  "%${empty_block_count}s" ""
context_bar="${filled_run// /█}${empty_run// /░}"
context_bar_color=$(tokens_to_color "$context_input_tokens")

# "180k/400k" under budget; "470k/400k +70k" once past it.
over_budget_part=""
(( context_input_tokens > handoff_budget_tokens )) &&
  over_budget_part=" +$(humanize_tokens $(( context_input_tokens - handoff_budget_tokens )))"

second_line="$(printf '%bctx %b%s %4s%b/%s%s%b' \
  "$color_dim" \
  "$context_bar_color" "$context_bar" "$(humanize_tokens "$context_input_tokens")" "$color_dim" \
  "$(humanize_tokens "$handoff_budget_tokens")" \
  "$over_budget_part" "$color_reset")"

five_hour_segment=$(build_limit_segment "5h" "$five_hour_percent" "$five_hour_reset_epoch" 18000 3600)
seven_day_segment=$(build_limit_segment "7d" "$seven_day_percent" "$seven_day_reset_epoch" 604800 86400)

[ -n "$five_hour_segment" ] && second_line="${second_line} ${color_dim}│${color_reset} ${five_hour_segment}"
[ -n "$seven_day_segment" ] && second_line="${second_line} ${color_dim}│${color_reset} ${seven_day_segment}"

# Spend: tracked only while a window is exhausted, i.e. while on usage credits.
# Each session writes its running cost to spend/<date>/<session_id>; summing
# those gives today's and this month's totals across sessions, and the month's
# per-day ledger is rewritten to spend/<YYYY-MM>.tsv. Session cost includes any
# usage from before the limit hit, so the figures are an upper bound.
monthly_budget_usd=500
if (( five_hour_percent >= 100 || seven_day_percent >= 100 )) && [ -n "$session_id" ]; then
  spend_root="$HOME/.claude/spend"
  spend_dir="$spend_root/$(date +%F)"
  mkdir -p "$spend_dir" && printf '%s\n' "$session_cost_usd" > "$spend_dir/$session_id"
  month=$(date +%Y-%m)
  for day_dir in "$spend_root/$month"-*/; do
    printf '%s\t%s\n' "$(basename "$day_dir")" "$(cat "$day_dir"* | awk '{t+=$1} END {printf "%.2f", t}')"
  done > "$spend_root/$month.tsv"
  day_cost_usd=$(awk -v d="$(date +%F)" '$1==d {print $2}' "$spend_root/$month.tsv")
  month_cost_usd=$(awk '{t+=$2} END {printf "%.0f", t}' "$spend_root/$month.tsv")
  second_line="${second_line} ${color_dim}│${color_reset} ${color_red}\$$(printf '%.2f' "$session_cost_usd")${color_reset} ${color_dim}(day \$${day_cost_usd} · mo \$${month_cost_usd}/\$${monthly_budget_usd})${color_reset}"
fi

printf '%b\n' "$second_line"
