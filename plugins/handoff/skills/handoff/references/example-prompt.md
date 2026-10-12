# Example handoff prompt (gold standard)

A real handoff prompt produced by this skill, with its results and paths replaced by placeholders, for the task "do the §6.2 size × grade
realizable-fraction valuation" in a timber-accounting research repo. It follows a session
that had just shipped a related valuation layer, so it leans heavily on *inherit the
frame* and *don't rebuild*. Note the grounding: exact `§` numbers, verified file paths,
an out-of-repo canonical source, decisions with explicit leans, and an early caveat with
a concrete pivot. Use it as a model for depth and specificity — not as a template to copy
verbatim (the section *shape* lives in `SKILL.md`).

Two things to calibrate against rather than imitate blindly. This is a **rich, doc-heavy
project**: numbered docs, a manuscript, fitted artifacts, a real test suite. A thinner
project should yield a proportionally shorter prompt, not a padded one at this length.
And the read-first entries here work because each one *states the commitment it carries*
("the boundary is a log-level phenomenon; QMD is the wrong unit"), not merely because
they cite a section number — that is the part worth copying.

---

```text
Goal: Agenda item #2 / §6.2 — draw the timber asset boundary at the (SIZE × GRADE)
log level, valuing the STANDING stock as
    V = Σ_{size s, grade g, species}  volume(s,g) · price(s,g) · realizable(s)
instead of pricing whole stands at a species-tier price × a QMD-indexed Pr(H). This
operationalizes the §6.5 "double hurdle": the hardwood premium (e.g. white-oak stave/
veneer) requires size AND grade JOINTLY, and dynamic high-grading makes those two
NEGATIVELY correlated in the standing survivor pool — so premium-eligible volume is the
small intersection, and naively valuing standing large hardwood at (large volume × stave
premium) overstates badly. The deliverable measures the (size × grade) composition of
the standing pool, prices it with the premium applied ONLY to the high-grade large
fraction (treated as an UPPER BOUND), and quantifies the overstatement. This is the
VALUE-side refinement that complements the realization×discount work just merged (EDRV,
era `valuation-1-edrv`, PR #9): EDRV refined *when/whether* realization happens at the
size level; §6.2 refines *which volume carries which price* at the size×grade level. It
does NOT touch the production south-2 stand model.

The empirical spadework already exists for white oak: the §7 feasibility study found the
(A) high-graded-residual signature (high-grade share collapses ~<a>%→<b>% while cull rises
~<c>%→<d>% across the oversized tail; premium-eligible fraction peaks ~<e>% and falls to
~<f>%; naive large×stave overstates <k>×). §6.2 is the VALUATION that turns that profile
into an asset number, generalized across hardwood groups.

== Read first (inherit the frame) ==
- docs/06_econometric_review.md §6.2 (the boundary is a log-level phenomenon; QMD is the
  wrong unit for marketability; V = Σ volume(s,g)·Pr(realize|s,g)·price(s,g)), §6.5
  (quality selection / high-grading; the double hurdle; observed grade is an UPPER BOUND
  on premium eligibility; the A-vs-B fork), §6.10 (agenda #2 and #6).
- docs/07_tree_level_feasibility.md — the white-oak grade-by-diameter profile is ALREADY
  computed here (the (A) signature, the premium-eligible fraction, the <k>× naive
  overstatement). Reuse/extend it; reproduce via scripts/plot_tree_level_feasibility.py
  (queries the 13 local per-state FIA DuckDBs at ~/Data/fiadb/
  <STATE>.duckdb; figs docs/figures/fig07_white_oak_grade_by_diameter.png).
- docs/09_edrv_valuation.md + src/harvest_prob/valuation.py — the JUST-MERGED EDRV layer:
  the realizable-fraction/realization side, and the representative-cell + TPA aggregation
  + price-linearity pattern to REUSE (size × ... cells, aggregate by FIA TPA).
- docs/modeling_principles.md 2 (boundary in volume-space at the log level — a tree is
  partly in, partly out), 8 (hardwood value is selected on quality; price the size×grade
  composition; observed high-grade = upper bound), 10 (conservatism is the preferred
  error direction).
- src/harvest_prob/models/white_oak.py — existing white-oak grade features
  (GRADE_HIGH_PROP, CULL) and the report-§15 null (grade does NOT predict stand-level
  harvest — the §6.5 level argument: high-grading is a within-stand tree act).
- src/harvest_prob/constants.py — HARDWOOD_VALUE_TIERS ($/ton by species group), the
  size×grade thresholds the manuscript used (stave ≥11", veneer ≥16–18"; sawtimber pine
  9"/hardwood 11" FIA-standard).
- The canonical manuscript (OUTSIDE the repo):
  ~/Documents/research/<project>/manuscript_v0.9.docx — how it priced
  hardwood (by SPECIES value tier, NOT by grade-within-species — so §6.2 is exactly the
  refinement it left undone) and its white-oak result ($<V>B, <r>% realization, "highest
  price / lowest realization") to reproduce/bracket.
- The project journal for harvest-prob (read at session start; append a dated progress
  note at session end) — include a line like this ONLY when the project actually keeps
  a journal, and point at the real one.

== What already exists (don't rebuild) ==
- THE PANEL: data/south_panel/tree_panel.parquet (3.15M at-risk tree-intervals) with, at
  T0: TREEGRCD_T0 (FIA tree grade), TREECLCD_T0 (tree class), CULL_T0 (% cull),
  DIA_BEGIN/DIA_T0, VOLCFNET_T0 (net cubic-ft growing-stock vol), VOLBFNET_T0 (sawtimber
  board-ft vol), DRYBIO_AG_T0 (dry tons), TPA_UNADJ_T0, SPCD, SFTWD_HRDWD,
  FOREST_TYPE_GROUP, TMS_REGION, SICOND_T0. This is the standing-stock (size × grade ×
  species) substrate — no new FIA pull needed for the panel itself.
- THE REALIZATION SIDE: the EDRV layer (src/harvest_prob/{models/edrv.py, valuation.py,
  models/growth.py, data/fvs_growth.py}) and the tree-2 hazards
  (data/south_panel/reports/tree_harvest_types_params.json). Size-indexed realizable
  fraction is available; REUSE rather than refit. Note: the hazard is size+species(S/H),
  NOT grade — see decision 4.
- PRICES: StumpagePriceLoader (timber_prices.duckdb) gives sawtimber/pulpwood by
  species/region. It does NOT price by grade — see the caveat.
- docs/07 white-oak grade-by-diameter machinery (scripts/plot_tree_level_feasibility.py).
- NO size×grade valuation code exists yet — this is greenfield (likely src/harvest_prob/
  valuation.py companions or a new module; reuse the cell/aggregation pattern).

== Decisions to settle WITH ME before heavy implementation ==
1. PRICE SCHEDULE by (size × grade) — the crux. TMS gives only saw/pulp by species; the
   stave/veneer/high-grade premium and the low-grade/cull discount need a source. Options:
   (a) absolute premium $ from an external grade-price source if one exists; (b) a
   premium/discount MULTIPLIER schedule over the TMS sawtimber base (e.g. veneer ×N,
   prime sawlog ×M, commodity ×1, cull→pulp), sourced from literature/assumption and run
   as a SENSITIVITY; (c) composition-only (report premium-eligible volume fractions, defer
   $). I lean (b) with a documented multiplier schedule + sensitivity — confirm, and tell
   me the source/values if you have them.
2. GRADE → PRODUCT mapping: how FIA TREEGRCD/TREECLCD/CULL map to {veneer/premium,
   prime sawlog, commodity sawlog, pulpwood, cull/non-merch}, and the size thresholds for
   premium eligibility (stave ≥11", veneer ≥16"?). Confirm the buckets and thresholds.
3. SCOPE: hardwood-focused (white oak the marquee, then all hardwood groups), with
   softwood handled simply (grade matters far less)? Or all species symmetric? I lean
   hardwood-focused.
4. REALIZATION × GRADE interaction: for STOCK valuation, §6.5 says condition on the
   survivor pool (don't de-bias). I lean: realizable(s) is SIZE-indexed (from the EDRV
   layer or south-2 Pr(H)); grade enters through PRICE ELIGIBILITY only (premium applied
   to the high-grade large fraction, observed grade as an upper bound), NOT through a
   grade-dependent harvest probability (the §15 null + selection confound). Confirm.
5. UPPER-BOUND haircut: how to encode "observed FIA high-grade is an upper bound" — apply
   a fixed eligibility haircut, or report the observed fraction as the ceiling and a
   plausible range below it? Confirm.
6. COMPOSE WITH EDRV or stand alone first: do §6.2 as a standing-stock (size×grade)
   composition+valuation first, then show how price(s,g) slots into the EDRV integral?
   I lean standalone-first, with the integration noted. Confirm.
7. VALIDATION anchors: reproduce/bracket (i) the docs/07 white-oak profile numbers
   (high-grade <a>%→<b>%, cull <c>%→<d>%, premium-eligible ~<e>%→<f>%, naive <k>× overstatement)
   and (ii) the manuscript white-oak $<V>B / <r>%. Confirm these are the targets.

== Deliverables ==
- A (size × grade × species) standing-stock COMPOSITION + realizable-fraction valuation
  (pure-array/Polars core where possible, CI-safe — mirror the EDRV core/aggregation
  split): standing volume by cell from the panel (TREEGRCD/CULL/DIA × VOLCFNET/VOLBFNET ×
  TPA), priced with the size×grade schedule, realizable-weighted; outputs the
  premium-eligible volume fraction and the OVERSTATEMENT vs a naive (large × premium)
  valuation, by species/group.
- Grade-by-diameter profile figures extended from white oak to all hardwood groups
  (the §6.5 A-vs-B test per group); the premium-eligible-fraction figure; era-stamped.
- A script (scripts/) running the full size×grade valuation + the multiplier sensitivity;
  era-stamped JSON/parquet outputs.
- Validation against the docs/07 profile + the manuscript white-oak number (bracket, like
  EDRV — this is a different, more conservative log-level estimator).
- Tests (composition fractions recover hand-checked cases; the double-hurdle intersection
  is smaller than either margin; upper-bound haircut monotonic; pure-array core, no DB).
- Short docs (new docs/10 OR extend docs/06 §6.2/§6.5; wire docs/00_index; add a model
  era only if warranted — e.g. `valuation-2-size-grade` — keeping CURRENT_CODE_ERA =
  south-2; update docs/model_versions.md).
- Branch + small focused commits; open PR; review; merge after my OK.
  IMPORTANT: per ~/.claude/CLAUDE.md, NO Claude promotion in commits/PRs (no
  Co-Authored-By: Claude, no "Generated with Claude Code"). Verify it runs before
  claiming done.

== Caveat to surface EARLY ==
The (size × grade) PRICE schedule is this task's external-dependency risk (the §6.2
analog of FVS last session): FIA TREEGRCD is sawtimber-only, coarse, crew-assigned, and
misses fine form defects, and TMS does not price by grade. So absolute premium dollars
depend on a grade-price source we may not have. Confirm decision 1 with me FIRST — if
there's no defensible premium-price source, we pivot the deliverable to a COMPOSITION +
premium-eligible-fraction + multiplier-sensitivity result (still the core §6.2/§6.5
contribution: the boundary in volume-space and the white-oak overstatement), rather than
a single absolute $ figure. Also check FIA grade COVERAGE in the panel up front (which
trees are graded at all) and tell me before building.

Start by reading the frame + docs/07 + checking FIA grade coverage in the panel, confirm
the decisions with me, then implement.
```
