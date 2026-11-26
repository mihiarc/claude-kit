# Questions waiting on you

Answer by number in the chief-of-staff session (`1 yes, 2 a`). Answered questions move to the end; none is deleted.

Next free number: 6 · Next command: C1

## By work type

### Admin (access, contracts, approvals, scheduling, commands only the user runs)

- **Renew the demo domain.** It lapses next week; the registrar needs a card on file. Demo site.

### Writing (papers, memos, notes to people, reviewing others' writing)

- **Review the methods draft.** The draft is in the shared folder and waits on your comments. Example paper.

### Building: data & science (estimators, models, datasets)

### Building: services & APIs (backends, data services)

- **Merge example-repo #12.** Checks pass; it adds the health route. Example service.

### Building: agents (harness, agent configs, evals)

### Building: apps & UI (what users click)

- **Try the new settings page.** It is deployed to staging and needs one click-through. Example app.

### Building: infra & ops (cloud, deploys, IAM, accounts)

## Where things stand

### Example service

- **Status:** Waiting on you — one merge
- **Now:** The health route is ready in example-repo #12.
- **Next:** You merge; the session deploys on **2026-11-21**.

## Open, by rank

### 1. [services] Example service: which database for the cache?

The cache needs a store before the deploy.

**Your call:** pick a store. **Lean: (a)**, because it is already running.

**Rank:** blocks the deploy since 2026-11-19; reversible.

**For:** you

**Asked by:** example-service--cache, waiting to write the cache layer.

**Options**

1. **(a) Reuse the existing store.** No new cost.

2. **(b) Add a dedicated store.** Isolates load; small monthly cost.

**Facts**

- The existing store has spare capacity.

Refs: example-repo #12

### 2. [writing] Example paper: submit to which venue?

The draft is close to done.

**Your call:** yes or no on the spring venue. **Lean: yes**, because the deadline fits.

**Rank:** not blocking yet.

**For:** you

**Asked by:** example-paper--draft, waiting to format the submission.

## Waiting on others

- [data] **Get the field plots from the partner team.** They promised the export by Friday; check back then. Example study.

### 4. [apps] Example app: which colour for the warning banner?

The design review will settle the palette first.

**Your call:** pick a colour. **Lean: (a)**, because it matches the brand.

**Rank:** not blocking.

**For:** you

**Asked by:** example-app--banner, waiting to style the banner.

**Options**

1. **(a) Amber.** Matches the brand.

2. **(b) Red.** Louder.

## Someday

- [writing] **Write up the onboarding notes.** Useful, but nothing waits on it. Example app.

## PRs ready to merge

| PR | Base | What it does | Head | Checks | Verified by | Reviewed by | Waits on |
|---|---|---|---|---|---|---|---|
| example-repo #12 | main | adds the health route | abc1234 | pass | tests pass; route returns 200 | fresh subagent; fixed a failing test | you |
| example-repo #13 | main | renames the config flag | def5678 | pass | tests pass | missing | review |

## Commands for you to run

## Done

- [infra, done 2099-01-01] **Rotate the staging key.** Rotated and the old key revoked. Example service.
- [admin, done 2000-01-01] **Book the venue.** Booked long ago, so it is outside the Done window. Demo site.

## Answered

### 5. [agents] Example agent: keep the old prompt?

**Answered** 2099-01-01 by you: no, use the new one.

### 3. [admin] Demo site: keep the old domain?

**Answered** 2000-01-01 by you: no.
