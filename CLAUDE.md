# claude-kit

This repo is public. Skills here are written for anyone: no employer, client or colleague names, no personal paths or account IDs. Specifics a skill needs, such as where files live, what is confidential, or how cloud resources are tagged, belong in the user's own CLAUDE.md, and the skill tells Claude to read them from there.

A pre-commit and pre-push hook runs `scripts/check-private-terms.sh` against `.git/info/private-terms`, a local list that is never pushed. When it blocks, generalize the text; don't edit the list to get a commit through.

Each plugin under `plugins/` has its own `.claude-plugin/plugin.json`, and `.claude-plugin/marketplace.json` lists them all. Check changes with `claude plugin validate .` and `claude plugin validate plugins/<name>`.
