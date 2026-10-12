#!/usr/bin/env bash
# Starting hit list for a residue sweep. Every hit needs reading; some are legitimate.
# Usage: residue_grep.sh <repo-root> [extra-pattern ...]
set -euo pipefail
root="${1:?repo root}"
shift || true

pattern='renamed|formerly|previously|no longer|moved (from|to)|now (uses|lives|is)|since the (refactor|rewrite|squash)|after the (refactor|squash)|per the review|\bPR ?#?[0-9]+|migration 0*[2-9]|TODO|FIXME|XXX|HACK|for now|temporar|prototype|\bwe\b|\bour\b|instead of|rather than|used to|the old\b|legacy'
for extra in "$@"; do pattern="$pattern|$extra"; done

grep -rn -i -E "$pattern" "$root" \
  --include='*.py' --include='*.md' --include='*.toml' --include='*.yml' --include='*.yaml' \
  --include='*.sh' --include='*.env*' --include='Dockerfile*' --include='*.sql' --include='*.ts' --include='*.tsx' --include='*.js' \
  --exclude-dir=.git --exclude-dir=.venv --exclude-dir=node_modules --exclude-dir=__pycache__ --exclude-dir=.archived \
  || echo "no hits"
