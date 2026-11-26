# Example opening record

The opening `## Progress` section for one task in a household-energy research repo: "estimate
heating demand at the building-age × insulation level". It is a worked example with results and
paths replaced by placeholders. It was written by a session that had just merged a related
weather-normalization layer, so it leans on *already exists* and *settled*. Note the grounding:
exact § numbers that each state the commitment they carry, verified paths, an out-of-repo
source, decisions settled before the record was written, one question left open with a lean,
and checks that define done. Done and Next are empty because the working session fills them.

Calibrate rather than copy. This is a doc-heavy project with numbered docs, a manuscript and a
test suite; a thinner project should give a shorter record, not a padded one at this length.

---

```markdown
## Progress

Task: Estimate HEATING demand at the (building age × insulation class) level,
    D = Σ_{age a, insulation i, region} floor_area(a,i) · intensity(a,i) · occupied(a),
instead of a region-wide average intensity × a degree-day index. This is §6.2 of the review,
and the demand-side complement to the weather layer merged in PR #9: that layer refined WHEN
demand happens through the year; this one refines WHICH floor area carries WHICH intensity. The
result is the retrofit-eligible share of floor area and how far a naive (old stock × worst
intensity) estimate overstates it, by region.
Risk: survey coverage. The insulation field is filled only for audited dwellings; check what
share of floor area has a class at all before building. If it is too thin, deliver the
composition and shares for the audited subset and say so, with no national total.

### Read first
- docs/06_method_review.md §6.2: the gap is a building-level phenomenon; the regional average
  is the wrong unit for retrofit eligibility. §6.5: eligibility needs age AND insulation
  jointly, and past retrofits make them negatively correlated in today's stock, so observed
  poor insulation is an UPPER BOUND on eligibility.
- docs/07_building_level_feasibility.md: the pre-1950 insulation-by-age profile is already
  computed (poorly insulated share <a>%→<b>% across the oldest cohorts; naive overstatement
  <k>×). Reproduce it with scripts/plot_building_level_feasibility.py, which reads the survey
  extracts under <data-dir>/housing-survey/.
- docs/modeling_principles.md rule 10: conservatism is the preferred error direction.
- The manuscript, outside the repo: <documents-dir>/<project>/manuscript_v0.9.docx. It
  estimated demand by regional average, not by building class, which is the gap this task
  fills. Its pre-1950 result is <V> TWh at <r>% occupancy.

### Already exists (don't rebuild)
- data/panel/dwelling_panel.parquet: 1.2M dwelling-years with AGE_BAND, INSUL_CLASS,
  FLOOR_AREA, HEAT_FUEL, WEIGHT. The (age × insulation × region) substrate; no new survey pull.
- src/heat_demand/weather.py: the weather layer. Reuse its representative-cell and
  weight-aggregation pattern and its age-indexed occupancy share; don't refit.
- src/heat_demand/constants.py: REGION_GROUPS and the manuscript's age thresholds.
- No age × insulation estimator exists yet; it goes in a new module beside weather.py.

### Settled
- Intensity schedule: a MULTIPLIER over the regional base intensity (uninsulated ×N, partial ×M,
  modern ×1, passive → floor), run as a sensitivity. The source has no metered intensities by
  class, so absolute intensities are out. (<user>, <date>)
- Insulation enters through intensity only, not through an insulation-dependent occupancy rate:
  the report's §15 null shows insulation does not predict vacancy. (<user>, <date>)
- Detached houses first, pre-1950 stock as the marquee case; flats estimated simply.
  (<user>, <date>)
- Averaging whole regions is what the manuscript did and what this task replaces. Don't fall
  back to it when a cell is sparse; report the cell as sparse.

### Done when
- The docs/07 pre-1950 profile reproduces within rounding, and the new estimator brackets the
  manuscript's <V> TWh from below.
- Tests pass (`uv run pytest`), including: the age-and-insulation intersection is smaller than
  either margin; the eligibility ceiling is monotone in the haircut; the core runs on arrays
  with no database.
- Insulation-by-age figures for every region, and the overstatement table by region, written
  by one script under scripts/.
- Small commits on this worktree's branch and an open PR; merge after the user's OK.

### Out of scope
- The production forecasting model and its price elasticities.
- Trap: a fudge factor that makes the age × insulation total match the manuscript. The point
  is to measure how far the regional-average method overstates, so a gap is the result, not a
  bug.

### Open questions for <user>
1. Age thresholds: pre-1950 and pre-1980 cohorts, as in the manuscript? I lean yes, so the
   result stays comparable to it.

### Done

### Next

### Branch
- worktree-age-insulation, from main at <sha> (PR #9 merged). Nothing committed yet.
```
