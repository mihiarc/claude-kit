# Subagent brief for a residue sweep

Fill the bracketed fields and send to an Opus-class agent. Keep the categories and the
"do not" list intact; they are the contract.

---

Repo: [absolute path], branch `[branch]` (verify with `git status -sb`; do not switch, do not
push). Toolchain: [e.g. `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`,
`uv run alembic check`]. [Any service the tests need, e.g. `docker compose up -d`.]

Goal: the code should read as if it had been written this way from the start. Sweep every
file (`src/`, `tests/`, [migrations dir], `scripts/`, `*.md`, `pyproject.toml`, `.env.example`,
compose and Docker files, `.github/`) for development residue and remove it. Behavior must
not change.

Names removed or renamed recently, which stale text may still cite: [list them: old module
paths, constants, functions, files, migration numbers, person names, PR numbers].

Categories and what to do:

1. Historical narration in comments/docstrings: anything explaining what code used to be or
   why it changed rather than what it is. Rewrite to the current fact or delete. `git log`
   is the history.
2. Design-argument text defending a choice against an alternative not in the tree. Keep one
   sentence of rationale where it prevents a likely mistake; cut the rest.
3. Stale references: names that no longer exist, section pointers ("§3.4", "see X") that do
   not resolve (check the target doc's headings: [paths to planning docs]), command lines
   naming old scripts, revision numbers other than the current ones.
4. Dead code: unused imports, functions, constants, `__all__` entries, fixtures and fixture
   parameters, settings fields, commented-out code, deferred imports without a cycle to
   justify them. Linter for imports, then grep or AST over every definition for a single
   occurrence. Search the whole repo for callers, not only the source package: migration
   env files, scripts, CI workflows and shell scripts import from the package too, and
   neither lint nor tests load them. Check declared dependencies against imports both ways; report an undeclared
   direct import rather than adding it.
5. TODO/FIXME/XXX/HACK/NOTE and prose hedges ("for now", "temporary", "prototype"): resolve
   or delete; a genuine open item becomes a one-liner in a README "Open items" section.
6. Docs: README and CLAUDE.md describe the current tree only; no change narration; no
   duplicated paragraphs between them (rules in CLAUDE.md, setup/layout in README, link
   across); `.env.example` matches the settings class field for field.
7. Test residue: debug prints, skips without reason, names describing old behavior, comments
   citing removed things, files written and never read.
8. Consistency: uniform docstring style, declarative tone, no first person, one spelling
   convention, no emoji, every module has a docstring.

Do NOT: change behavior, rename public functions, alter migration SQL, touch `.git`, or
delete rationale for constraints the repo's conventions call "the design".

Method: run [skill path]/scripts/residue_grep.sh [repo] as a starting list, then read every
file top to bottom anyway.

Finish: full check suite (paste output verbatim), `git diff --stat`. [If the user asked for a
commit: one commit with a concise message stating what the tree now is, no attribution lines.
Otherwise leave the changes uncommitted.] Never push. Report: verification
output verbatim; one line per file grouped by category (trivial ones grouped); items left
deliberately with reasons; open items moved to README.
