#!/usr/bin/env python3
"""PreToolUse guard: refuse to delete a branch that open pull requests are based on.

When a PR's base branch is deleted, GitHub closes that PR instead of retargeting
it. This blocks the two ways that happens from the shell:

- ``gh pr merge <pr> --delete-branch`` (or ``-d``), when an open PR is based on
  the merging PR's head branch;
- ``git push <remote> --delete <branch>`` / ``git push <remote> :<branch>``, when
  an open PR is based on ``<branch>``.

It only ever denies; otherwise it prints nothing, so the normal permission flow
applies. If a gh lookup fails (no network, no auth, not a GitHub repo) the
command proceeds.
"""

import json
import sys

raw = sys.stdin.read()
if "gh pr merge" not in raw and "git push" not in raw:
    sys.exit(0)

import os  # noqa: E402
import shlex  # noqa: E402
import subprocess  # noqa: E402

# gh pr merge flags that take a value (long and short forms)
VALUE_LONG = {"--repo", "--body", "--body-file", "--subject", "--author-email", "--match-head-commit"}
VALUE_SHORT = set("RbFtA")
SAFE_LOOP = (
    "GitHub CLOSES a PR whose base branch is deleted; it does not retarget it. Safe order:\n"
    "  1. gh pr merge <PR> --squash            (no --delete-branch)\n"
    "  2. gh pr edit <dependent> --base main   (retarget before deleting anything)\n"
    "  3. if squash-merged: from the top branch, git rebase --onto origin/main <merged-branch> --update-refs,\n"
    "     then force-push the remaining branches and let CI run\n"
    "  4. only then delete the merged branch (git push origin --delete <branch>)\n"
    "Recovery if a PR already closed: re-push its base branch, gh pr reopen, gh pr edit --base main. "
    "See ~/code/papercuts.md."
)


def segments(command):
    """Split a shell command into simple commands at &&, ||, ;, | and friends."""
    lex = shlex.shlex(command, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    tokens = list(lex)
    seg = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok and set(tok) <= set("<>&") and ("<" in tok or ">" in tok):
            # Redirection: drop it, its target, and a file-descriptor number before it
            if seg and seg[-1].isdigit():
                seg.pop()
            i += 2
            continue
        if tok and set(tok) <= set("&|;()"):
            if seg:
                yield seg
            seg = []
        else:
            seg.append(tok)
        i += 1
    if seg:
        yield seg


def gh_json(args, cwd):
    out = subprocess.run(
        ["gh", *args], cwd=cwd, capture_output=True, text=True, timeout=15, check=True
    )
    return json.loads(out.stdout)


def open_prs_based_on(branch, repo, cwd):
    args = ["pr", "list", "--base", branch, "--state", "open", "--json", "number,title"]
    if repo:
        args += ["--repo", repo]
    return gh_json(args, cwd)


def parse_gh_pr_merge(args):
    """Return (selector, repo, deletes_branch) for the arguments after `gh pr merge`."""
    selector, repo, delete = None, None, False
    i = 0
    while i < len(args):
        tok = args[i]
        if tok.startswith("--"):
            name, _, value = tok.partition("=")
            if name == "--delete-branch":
                delete = value.lower() not in ("false", "0") if value else True
            elif name == "--repo":
                repo = value or (args[i + 1] if i + 1 < len(args) else None)
            if name in VALUE_LONG and not value:
                i += 1
        elif tok.startswith("-") and len(tok) > 1:
            letters = tok[1:]
            for j, ch in enumerate(letters):
                if ch == "d":
                    delete = True
                if ch in VALUE_SHORT:
                    rest = letters[j + 1 :]
                    if ch == "R":
                        repo = rest or (args[i + 1] if i + 1 < len(args) else None)
                    if not rest:
                        i += 1
                    break
        elif selector is None:
            selector = tok
        i += 1
    return selector, repo, delete


def parse_git_push_deletes(args):
    """Branch names a `git push` deletes (after `push`)."""
    delete_flag = any(a in ("--delete", "-d") for a in args)
    positionals = [a for a in args if not a.startswith("-")]
    branches = []
    if delete_flag:
        branches += positionals[1:]  # first positional is the remote
    branches += [p[1:] for p in positionals[1:] if p.startswith(":") and len(p) > 1]
    return [b.removeprefix("refs/heads/") for b in branches if not b.startswith(":")]


def deny(reason):
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    sys.exit(0)


def main():
    payload = json.loads(raw)
    command = payload.get("tool_input", {}).get("command", "")
    cwd = payload.get("cwd") or os.getcwd()

    for seg in segments(command):
        if seg[0] == "cd" and len(seg) > 1:
            cwd = os.path.normpath(os.path.join(cwd, os.path.expanduser(seg[1])))
            continue

        if seg[:3] == ["gh", "pr", "merge"]:
            selector, repo, delete = parse_gh_pr_merge(seg[3:])
            if not delete:
                continue
            view = ["pr", "view", "--json", "number,headRefName,baseRefName,isCrossRepository"]
            if selector:
                view.insert(2, selector)
            if repo:
                view += ["--repo", repo]
            pr = gh_json(view, cwd)
            if pr.get("isCrossRepository"):
                continue  # the head branch lives in a fork; no PR here is based on it
            dependents = open_prs_based_on(pr["headRefName"], repo, cwd)
            if dependents:
                listed = ", ".join(f"#{d['number']} ({d['title']})" for d in dependents)
                deny(
                    f"Blocked: `gh pr merge #{pr['number']} --delete-branch` would delete "
                    f"`{pr['headRefName']}`, the base of open PR(s) {listed}. "
                    f"Retarget them to `{pr['baseRefName']}` first.\n" + SAFE_LOOP
                )

        elif seg[:2] == ["git", "push"]:
            for branch in parse_git_push_deletes(seg[2:]):
                dependents = open_prs_based_on(branch, None, cwd)
                if dependents:
                    listed = ", ".join(f"#{d['number']} ({d['title']})" for d in dependents)
                    deny(
                        f"Blocked: deleting branch `{branch}` would close open PR(s) based on it: "
                        f"{listed}. Retarget them first (gh pr edit <N> --base main).\n" + SAFE_LOOP
                    )


try:
    main()
except Exception:  # fail open: a lookup problem must not block the command
    sys.exit(0)
