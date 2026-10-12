---
name: disk-cleanup-inventory
description: >-
  Build a tiered inventory of what's eating disk space, deliver it as an interactive HTML
  worksheet the user checks off, then delete the selections safely with review-before-rm and
  explicit paths. Scans with df/du, classifies every large item by how safe it is to remove
  (regenerable caches/envs → re-downloadable data → verify-first source data → downloads clutter),
  checks git-ignore/provenance, and never blind-deletes mixed folders. Triggers on "hard drive
  cleanup", "free up disk space", "what's taking up space", "inventory large files", "my disk is
  full", or any reclaim-space request across the disk or project trees. Not for tidying or sorting
  ~/Downloads itself: use downloads-tidy.
---

# disk-cleanup-inventory

Help the user reclaim disk space by producing an inventory they can *decide* against, then deleting only what they confirm. The whole point is judgment, not bulk deletion: most space lives in things that are regenerable (caches, virtualenvs, build artifacts, routing tiles) or re-downloadable (raw datasets, installers) — but mixed in with that are irreplaceable source data, results, and code that look similar by size. Separate them carefully.

**Cost rule**
- Delegate the scanning and classification legwork (Step 1 drill-downs, `du`/`find` sweeps, provenance checks, first-draft item lists) to a subagent on a lower-cost model (Sonnet or Haiku). Reserve the primary model for tier judgment calls, the worksheet, and anything that runs `rm`.

**Hard rules**
- Never delete without explicit per-run confirmation. Selecting items in the worksheet is intent; a "go" (or running the commands themselves) is authorization.
- Never blind-`rm` a directory that mixes disposable and keep-worthy content. Inspect it first and narrow the path (e.g. delete `project/data/raw`, keep `project/{code,outputs,docs}`).
- Use **explicit paths** for deletion, not a recursive `find … -exec rm` that can wander into a tree the user asked to keep.
- The worksheet runs nothing. Either the user runs the generated commands, or you run them after a "go".
- Look at any target before deleting — if what you find contradicts how it was described, stop and surface it.

## Procedure

### Step 1 — Scan, top-down

Run breadth-first and only drill into the biggest nodes. Don't `du` the whole home dir at full depth up front — it's slow and noisy.

```
df -h /                                            # how full, how much free
du -sh ~/*/ 2>/dev/null | sort -rh | head -20      # top-level home
du -sh <bigdir>/*/ 2>/dev/null | sort -rh | head   # drill into each biggest one, repeat
```

For a directory whose bulk you can't explain, profile by file type and find the giant files:

```
find . -type f -exec stat -f '%z %N' {} + 2>/dev/null \
 | awk '{n=split($2,a,"."); e=a[n]; s[e]+=$1; c[e]++} END{for(x in s) printf "%.1f GB  %d  .%s\n", s[x]/1073741824, c[x], x}' | sort -rh | head
find . -type f -size +500M -exec stat -f '%z %Sm %N' -t '%Y-%m-%d' {} + 2>/dev/null | sort -rn | head
```

Always sweep for the regenerable classics across the project tree(s):

```
find ~/Github ~/code ~/Data -name node_modules -type d -prune -exec du -sh {} + 2>/dev/null | sort -rh
find ~/Github ~/code ~/Data \( -name .venv -o -name venv \) -type d -prune -exec du -sh {} + 2>/dev/null | sort -rh
du -sh ~/Library/Caches/*/ | sort -rh | head     # Homebrew, Playwright, pnpm/Yarn, datalab, aws, etc.
```

### Step 2 — Classify each large item into a tier

Assign every item a tier by how safe deletion is. This ordering *is* the worksheet's structure.

1. **Safe / regenerable** — rebuilt in seconds, zero data loss: `node_modules` (reinstall), `.venv`/`venv` (`uv sync`), dependency/tool caches (Homebrew, Playwright, pnpm, Yarn, datalab, aws), Docker disk (`docker system prune`). *Don't* `rm` the Docker container blindly — use prune.
2. **Re-downloadable / generated data** — reproducible but takes time: pipeline outputs (tiles, derived rasters/geopackages), raw downloaded datasets, built databases (e.g. per-state DuckDBs from a public DataMart), routing tiles (rebuilt from OSM — keep the build scripts, delete only the tile data).
3. **Verify first** — re-acquirable but slow/large *and* possibly still in use: research source data, anything tied to an active analysis or manuscript. Confirm the work is finished before deleting.
4. **Downloads clutter** — app installers (`.dmg` for apps already installed), stray archive zips already extracted. List the big items here for the space total, but if the user wants ~/Downloads sorted or filed rather than just trimmed, hand that part to the downloads-tidy skill, which matches files against their real homes and trashes recoverably.

**Provenance checks that change the tier:**
- `git -C <repo> check-ignore <path>` / `git ls-files <dir> | wc -l` — is the data git-ignored (not backed up by VCS) or actually committed? Git-ignored bulk data is the canonical local-only copy, so re-download source must exist before deleting.
- Distinguish **raw input** (delete) vs **computed results/outputs** (usually keep — small and expensive to recreate) vs **code/docs** (keep). A folder is rarely uniformly disposable.
- Note last-modified dates — stale outputs are safer candidates than this week's.

### Step 3 — Deliver the interactive worksheet

Build an HTML worksheet from `assets/worksheet-template.html` and publish it with the **Artifact** tool. Load the `artifact-design` skill first for the visual build. The template already implements the interaction; your job is to fill the `ITEMS` array (one object per inventoried item: `id, tier, nm, gb, pth, note, review, del`) and the disk-gauge numbers.

The worksheet must let the user: check items, watch a live reclaimable-GB total, and copy a generated **review (`du`/`ls`)** block and a **delete (`rm`)** block for exactly their selections. Items needing a sub-path decision (tiers 3–4, mixed folders) get a *commented* `del` command so nothing runs blind.

If the user wants a copy they can keep, also write a standalone version into `~/Downloads/` — wrap the artifact file in `<!doctype html><html><head>…</head><body>…</body></html>` (the Artifact host adds that skeleton at publish time, so the raw file lacks it).

### Step 4 — Review before deleting

When the user has chosen (have them paste the worksheet's copied review block, or list item names), run the **read-only review first**: `du -sh` every directory and `ls -lhS` every glob. Confirm sizes are sane and every path resolves. Present the totals.

### Step 5 — Narrow scope, then delete on confirmation

Before running any `rm`:
- Ask what's **actively in use** and exclude it (e.g. "keep the envs for the projects I'm working on today" → drop those exact `.venv`/`node_modules` paths from the batch).
- For mixed folders, delete only the disposable sub-path (`…/data/raw`), keeping code/results/docs.
- For a selected *category* (e.g. "the zips"), separate big data dumps from small content (design assets, icons) and confirm the small stuff before including it.
- Confirm method: permanent `rm` (frees space immediately — right for regenerable items) vs. move to `~/.Trash` (recoverable, but space isn't freed until emptied).

Then execute with **explicit paths**, capturing space freed:

```
AVAIL_BEFORE=$(df -k ~ | awk 'NR==2{print $4}')
rm -rf ~/path/one ~/path/two …          # explicit, no wandering find across excluded trees
AVAIL_AFTER=$(df -k ~ | awk 'NR==2{print $4}')
echo "freed $(( (AVAIL_AFTER-AVAIL_BEFORE)/1048576 )) GB"
```

### Step 6 — Verify

Confirm the keeps survived and the deletes landed: list the preserved paths (e.g. active-project envs, kept code/docs), confirm the deleted ones are gone, and re-`du` the top-level dirs. Report space freed via `df` (the `du`-vs-`df` gap from APFS accounting is normal). Offer to clean up the worksheet file if one was written to disk.
