#!/usr/bin/env bash
# Install claude-kit into ~/.claude from a profile.
#
#   ./install.sh                     use ~/.claude/me/profile, or the defaults if there is none
#   ./install.sh --profile <path>    use that profile
#   ./install.sh --skip-repos        everything except cloning the profile's repos
#   ./install.sh --dry-run           say what would change and change nothing
#
# Safe to rerun. Any file it replaces is first moved aside as <file>.bak-<timestamp>.
# The work is done by installer/kit_install.py; installer/README.md describes the profile.
set -euo pipefail
kit=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
case ${1-} in -h|--help) sed -n '2,10p' "$0"; exit 0 ;; esac
command -v python3 >/dev/null 2>&1 || { echo "install.sh needs python3; install it and rerun" >&2; exit 1; }
exec python3 -I "$kit/installer/kit_install.py" install "$@"
