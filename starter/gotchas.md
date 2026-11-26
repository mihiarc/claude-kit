# Gotchas

Settled answers to tooling failures that cost time, grouped by tool under `## ` headings. Each entry is one line, written as symptom → what works. Open problems belong in your papercut log, and quirks of a single repo belong in that repo's CLAUDE.md.

The papercuts plugin's hook (`gotcha_hints.py`) reads this file and hands a session the one entry its command or error needs. It reads only lines that start with `- ` at the left margin, so this header holds none; with no entries the hook does nothing. An entry may end in an HTML comment holding its triggers, separated by `;`, each a Python regex:

    command:  searched in a Bash command before it runs; the entry arrives with that call's result
    deny:     like command, but a match blocks the call and shows the entry as the reason
    error:    searched, ignoring case, in a failed call's error text and in a Bash call's output
    tool:     the tool name must match; alone, the entry arrives with the session's first call to that tool
    in:       `worktree` limits command, deny and tool triggers to sessions in a linked git worktree

For example, an entry under a `## Shell` heading could read:

    - `/bin/bash` 3.2 on macOS has no `mapfile` → `while IFS= read -r l; do A+=("$l"); done < file`. <!-- command: \bmapfile\b; error: mapfile: command not found -->

An entry without a trigger is kept for reading and for the papercut sweep but never fires. The papercut-sweep skill moves settled entries here from the papercut log, and `python3 gotcha_hints.py check <this file>` reports bad regexes.
