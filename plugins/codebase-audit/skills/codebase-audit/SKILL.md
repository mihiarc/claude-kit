---
name: codebase-audit
description: >-
  Performs a full critical review of a whole codebase or a component: explores and orients,
  reads the source directly to judge correctness, security, reliability, architecture and
  maintainability, produces severity-rated findings, cross-references security/ops/architecture
  findings against current best practices via web search, and — only after the user confirms —
  files grouped, labeled GitHub issues. Use when the user asks to "review the codebase",
  "do a full/critical review", "audit this repo", "explore and critique", "find issues and file
  them", or "cross-reference against best practices". Not for reviewing only the current diff or a
  PR (/code-review), a security pass on pending changes (/security-review), or cleanup of changed
  code (/simplify).
allowed-tools:
  - Read
  - Grep
  - Glob
  - WebSearch
  - WebFetch
  - Bash(git log *)
  - Bash(git ls-files *)
  - Bash(gh issue list *)
  - Bash(gh label list *)
  - Bash(gh auth status *)
  - Bash(gh repo view *)
---

# Codebase audit

A four-phase pipeline: **orient → critically review → cross-reference → file issues**. The goal is a faithful, genuinely critical assessment that ends in tracked, actionable GitHub issues. Be direct about problems; this is a critique, not a summary. Note real strengths too.

Work the phases in order. Phases 1–3 are read-only and safe to run unprompted. **Phase 4 (filing issues) is outward-facing — never start it until the user explicitly confirms.**

## Phase 1 — Scope & orient

1. **Settle scope.** Whole repo, a subdirectory/service, or a set of files? If ambiguous and it materially changes the work, ask. Default to the repo root the user is in.
2. **Recon (read-only).** In parallel where possible:
   - Tree/layout, entry points, `README`/`CLAUDE.md`, package/dep manifests, CI workflows, Dockerfiles/build scripts.
   - `git ls-files` for tracked **`.env*` / secrets / config** files, and check `.gitignore` coverage.
   - Whether tests / linters exist (don't invent commands that aren't there).
   - Recent `git log` for context on what's WIP.
3. Note where the README/docs **disagree with the actual tree** — drift is itself a finding.

## Phase 2 — Critical review

**Read the source directly.** For correctness and security judgments you must read the actual code — do not rely only on summaries. Use `Explore`/subagents to *locate* code and map breadth, but form the critique yourself from the real files. For a small/medium codebase, read essentially all source modules.

Evaluate across these axes:
- **Correctness** — logic bugs, wrong SQL/queries, off-by-one, non-tuple params, broken control flow, swallowed errors.
- **Security & authz** — authentication/authorization gaps, secrets handling, injection, XSS, token exposure, over-broad IAM.
- **Reliability/ops** — error handling, idempotency, retries, state that won't survive restart/multi-replica, DLQ/queue handling, timeouts.
- **Architecture & maintainability** — duplicated/divergent implementations, implicit contracts between components, coupling, dead code.
- **Build/deploy/deps** — dependency pinning, reproducibility, broken or no-op build args, CI correctness, region/env mismatches.
- **Domain correctness** — for scientific/financial/domain numerics you cannot independently verify (magic constants, unit conversions, formulas), flag them as **"verify with domain owner; add a golden-value test"** rather than asserting they're right or wrong. State your reasoning and the specific uncertainty.

**Handling secrets:** if you find credentials in tracked files, assess privately — **never reproduce the secret values** in output. Report the exposure, recommend rotation + gitignore, and downgrade severity if the values turn out to be non-sensitive config.

**Finding format.** Rate every finding and keep each tight:

> **Severity legend:** 🔴 critical · 🟠 high · 🟡 medium · ⚪ low
>
> Each finding: **what** · **where** (`file:line`) · **why it matters** · **suggested fix**.

Group findings by severity. Open with a short honest **overall verdict** (maturity, biggest risks). Close with a prioritized next-steps list. Include a brief **"what's good (keep)"** section — a fair review names strengths.

## Phase 3 — Cross-reference against current practice

For the security / architecture / ops / dependency findings (not domain-science ones), run targeted `WebSearch` queries for **current** best practice (include the year). For each, state: what you flagged → what current practice says → **confirmed / refined / severity-adjusted**, and keep the authoritative source URLs (official vendor docs > reputable blogs). Fold sharpened recommendations back into the findings. End the cross-reference with a **Sources:** list of markdown links.

Domain/scientific correctness is **not** web-searchable — those still need a domain owner and tests; say so.

## Phase 4 — File GitHub issues (only after explicit confirmation)

1. **Confirm first.** Filing issues and creating labels are outward-facing — wait for an explicit go-ahead. Approval to file one batch does not extend to later ones.
2. **Pre-flight:** `gh auth status`, confirm issues are enabled and you have write access (`gh repo view --json hasIssuesEnabled,viewerPermission`), and list existing labels (`gh label list`). Check existing issues to **avoid duplicates** — skip findings already filed and cross-link related ones.
3. **Group sensibly.** One issue per distinct, actionable problem. Combine multiple bugs in the same function/file into one issue; bundle trivial cleanups into a single "[cleanup]" issue. Don't spam one issue per line.
4. **Write bodies to files, then `gh issue create --body-file`** (avoids shell-quoting problems). A good body: problem statement, location (`file:line`), impact, suggested fix, cross-referenced source links where relevant, and `#NN` links to related issues.
5. **Severity in the title.** If the repo has no severity labels, prefix titles with `[critical]`/`[high]`/`[medium]`/`[cleanup]`. Apply existing labels (`bug`, `documentation`, `enhancement`, …). If a `security` label is warranted and missing, **ask** before creating it; apply it only to genuinely security-relevant issues.
6. **Report a triage table** grouped by severity with the issue numbers/links, and suggest a sensible first sprint (small, high-impact items first). Offer to open a tracking/epic issue or a PR for the cheap, unambiguous fixes.

## Guardrails

- Be genuinely critical and specific — vague praise or hedged findings aren't useful. But don't manufacture severity; calibrate honestly and mark uncertainty.
- Don't claim something is broken without having read the code path. When you can't fully verify (e.g. behavior depends on a third-party lib's semantics), say "verify" and explain why.
- Correct yourself if a later finding contradicts an earlier label (e.g. mislabeling a functional bug as "security") — fix it rather than leaving it.
- Match the repo's reality (its actual tooling/region/conventions), not idealized defaults.
