---
name: residue-sweep
description: >-
  Make a repo read as if it had been written its current way from the start by removing
  development residue without changing behavior — comments and docstrings that narrate history
  ("renamed from", "now", "per the review"), arguments against alternatives nobody can see, stale
  references to removed names or migration numbers, dead code and undeclared/unused dependencies,
  TODO markers, README/CLAUDE.md drift, test leftovers. Use after a refactor, rename, migration
  squash or review-driven rewrite, before merge or handoff: "clean up the comments/docs after the
  refactor", "no baggage", "sweep for leftovers", "does this read like it was always this way", or
  when a review says docs describe old behavior. Not for disk or Downloads cleanup, or general
  code simplification (/simplify).
metadata:
  author: mihiarc
  version: "1.0"
---

# residue-sweep

Refactors leave a residue that `git diff` does not show: docstrings that explain what the code
*used to be*, comments that argue against an alternative no reader can see, references to
files and constants that no longer exist, a helper nobody calls, a TODO that was resolved by
the rewrite, a README paragraph that still narrates the change. None of it breaks tests, all
of it makes the next reader reconstruct history to understand the present. The goal of this
skill is a tree where every comment states a current fact and `git log` holds the history.

Behavior must not change. This is a reading and deleting job, verified by the existing
test suite, linter and any schema check the repo has.

## How to run it

**Delegate the sweep to an Opus-class subagent** and review its report rather than reading
every file yourself. The sweep is broad and self-contained; the judgment calls it
raises are few and come back in the report. Use the brief in `references/agent-brief.md`,
filling in the repo path, branch, toolchain commands and any repo-specific names that were
removed in the preceding work (the agent cannot know that `AOI_TYPES` or `session_scope`
used to exist unless told).

While the agent works, list the names you know were removed or renamed in this session and
send them if you forgot any. When it reports back:

1. Re-run the repo's checks yourself (tests, lint, format, schema/migration check). Trust
   the report's verbatim output only after you have reproduced it.
2. Run your own residue grep (`scripts/residue_grep.sh <repo>`) and read every hit. A few
   will be legitimate uses of the words; the rest are misses.
3. For every function, constant or config key the report says it deleted as unused, grep the
   whole repo yourself, including `alembic/`, `scripts/`, CI workflows, compose files and
   shell scripts. Agents tend to search the source package and call the rest "external".
   A first run of this skill deleted a helper that the Alembic `env.py` still imported;
   lint and the test suite both passed because neither loads that file.
4. Read the "left deliberately" section of the report and decide each item. Common ones:
   an undeclared dependency the agent would not add during a cleanup (declare it), a config
   field that looks unused but is read at runtime (keep), rationale for constraints that are
   the design (keep).
5. Commit only if the user asked for a commit; otherwise leave the changes in the working
   tree for them to review. Never push.

Whatever the agent reports, its report is where the errors hide, so steps 1 to 3 are not
optional.

## What counts as residue

The categories below are the checklist. Explain them to the agent in these terms; the
reasoning matters more than the word list because narration uses many words.

**Historical narration.** Any comment or docstring whose subject is a change rather than the
code: "renamed from", "formerly", "previously", "no longer", "moved from", "now uses",
"since the refactor", "after the squash", "per the review", a person's name, a PR number,
a migration number that no longer exists. Rewrite to the current fact, or delete when the
code already says it.

**Design arguments.** Docstrings that defend a choice against an alternative absent from the
tree ("we use X rather than Y because..."). Keep one sentence where it prevents a likely
mistake, for example why a constraint is kept only on authorization columns, or why
`SET LOCAL` is transaction-scoped. Cut the rest; planning docs and git history hold it.

**Stale references.** Names of modules, functions, constants, files or sections that do not
exist. Check every `§` or "see X" pointer against the actual heading or path. Check
command lines in docs against the actual script names.

**Dead code.** Unused imports, functions, constants, `__all__` entries, fixtures, fixture
parameters, settings fields, commented-out code, deferred imports with no cycle to justify
them. Use the linter for imports, then grep every definition in the source tree for a
single occurrence. Check declared dependencies against imports in both directions: an
unused declared dependency is residue, and a directly imported but undeclared one is a
latent break.

**Markers.** TODO, FIXME, XXX, HACK, NOTE. Resolve or delete. A genuine open item becomes a
one-line entry in a README "Open items" section, not a comment in code. Hedges in prose,
"for now", "temporary", "prototype", are markers in disguise; treat them the same way.

**Docs.** README and CLAUDE.md describe the current tree only. No "now", "became", "was
squashed". No duplicated paragraphs between the two: CLAUDE.md holds rules that bite in
code, README holds setup and layout, one links to the other. `.env.example` matches the
settings class field for field, because a blank line in the example overrides a default
with an empty string.

**Test residue.** Debug prints, skips without reason, tests named for old behavior, comments
referring to removed constraints or renamed files, files a test writes and never reads.

**Consistency.** Uniform docstring style, declarative comment tone, no first person, one
spelling convention, no emoji, and every module has a docstring.

## What not to touch

- Behavior, public names, migration SQL, lockfiles beyond what a declared-dependency fix
  needs.
- Rationale for constraints or invariants the repo's own conventions say are "the design".
  The test of whether a sentence stays is whether deleting it makes a plausible mistake
  more likely, not whether it is interesting.
- Anything in `.git`.

## Method the agent should follow

Start with the grep in `scripts/residue_grep.sh` as a hit list, then read every file top to
bottom anyway. Grep misses narration that uses other words, and misses stale references
entirely because they look like ordinary identifiers. For dead code, use an AST or grep
pass over every `def` and module-level constant, not only the linter's unused-import rule.

Finish with the repo's full check suite. If the user asked for a commit, make one, with a
message that states what the tree now is, not what was removed from it, and no attribution
lines. Never push.

## Report format

The agent's report and your summary to the user use the same shape, so the user can see
what changed without reading a diff:

- Verification output, verbatim.
- One line per file, grouped by category above. Trivial ones grouped into one line.
- Items left deliberately, each with the reason.
- Open items moved to README.
