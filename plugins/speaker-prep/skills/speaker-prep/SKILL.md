---
name: speaker-prep
description: >-
  Prepare a speaker to deliver a talk: turn a deck or brief into per-slide key messages, a timed
  script or talking points, a glossary, and delivery-formatted PDFs (large-print script with
  slide-advance cues, distribution copy, condensed outline). Modes are scripted, natural talking
  points, backup presenter covering someone else's slides, and no-slides remarks (elevator pitch,
  panel, intro). Use when the user wants a speaking script, talking points, speaker notes, talk
  timing, rehearsal help, or to prep as a backup speaker or in case they're "called on". Not for
  building or editing the slide deck itself: that is the pptx/slides tooling.
---

# Speaker Prep

Turn a deck (or a topic brief) into prep materials that make the speaker effective on the day: key messages per slide, timing that respects a hard budget, and documents formatted for how eyes actually move between page and audience.

## Core principles

These apply in every mode; they're why the workflow looks the way it does.

- **Key messages first.** One or two points per slide, chosen deliberately, beat comprehensive coverage. Even a speaker who will improvise benefits from deciding in advance what each slide is *for*.
- **Framing before writing.** The audience decides what lands. Capture 2–4 framing notes (not spoken lines) before drafting: what does this audience fund/approve/decide? What's the value proposition in *their* terms? What concrete names make it real for them? Every slide point should be checkable against these.
- **The expertise boundary is a design input.** Ask what the speaker can and can't speak to. Material outside their depth must come strictly from what's printed on the slides — readable off the screen, never improvised. Give them explicit deflection lines and a "never explain" list rather than hoping they'll wing it.
- **Timing is a budget, not a hope.** Measure the script in words, convert at 120–135 wpm, and build checkpoints, a cut-first list, and safe expanders. Running short is recoverable (pause, slow down); running over is not.
- **The speaker's voice wins.** Deliver an editable markdown file with a `**My additions:**` block per slide, expect the user to rewrite lines, and preserve their edits on every later pass. Bracketed questions they leave (like `[what is TRL?]`) are questions to you — answer them inline.
- **One markdown source, all outputs.** Script, delivery PDF, distribution PDF, and condensed outline all derive from the same file, so an edit propagates everywhere.

## Step 1 — Gather context

Read the deck first (PDF/pptx — use the document skills). Then establish, asking only for what the conversation hasn't already supplied:

1. **Mode** — scripted / natural / backup presenter / no slides (see modes below).
2. **Time budget** — total slot, the speaker's share, hard max, Q&A handling. Get real numbers; "about 20 minutes" and "20 minutes, strict" produce different documents.
3. **Audience + stakes** — who decides what, and on what basis. This becomes the Framing section.
4. **Slide ownership** — which slides are theirs; who handles the rest and Q&A.
5. **Expertise boundary** — what they can own vs. what must stay on-slide (critical in backup mode; useful in all modes).

## Step 2 — Draft the prep document (markdown)

One file, structured as:

```
# <Title — engagement, role, date>
## Framing (context, not spoken lines)   ← 2–4 audience/stakes bullets
## Ground rules                          ← opening line, deflection line, never-explain list, cue conventions
## Timing                                ← budget, per-slide targets, checkpoints, cut list, expanders
## Quick glossary                        ← terms the speaker needs for footing, one line each, "say this much and no more"
## Slide N — <title>                     ← one section per slide (or per message, in no-slides mode)
   ...content per mode...
   **My additions:**                     ← empty block for the speaker's voice
## Two threads to internalize            ← 1–2 sentences that connect everything, for recovery when lost
```

### Per-slide content by mode

**Scripted delivery.** Each slide gets a core **Say** block (the one or two chosen points, ~20–40s) and, when the time budget demands more, an **Expand** block. The critical constraint on Expand material: build it by walking what is printed on the slide — the workflow boxes, table rows, bullet lists. That triples airtime with zero risk, because the text is on screen behind the speaker. Mark risky slides (*"don't walk the diagram"*, *"stop there"*) and give built-in exit lines ("I'll leave the physics to Dr. X, but the picture is the intuition").

**Natural / extemporaneous.** No verbatim script. Each slide gets: the 1–2 key messages (as statements, not speech), 2–3 supporting facts pulled from the slide, and a one-line transition to the next slide. The value is the *choosing* — the speaker improvises the wording but never wonders what the slide is for.

**Backup presenter.** Scripted mode plus the boundary machinery: an opening handoff line explaining the substitution, a rehearsed deflection line for technical questions ("that's squarely Dr. X's area — let me take that back and we'll respond in writing"), a never-explain list of specific topics, and instructions to read labels rather than interpret diagrams. The glossary matters most here — it's for the speaker's footing, not for lecturing the audience.

**No slides (elevator pitch, panel remarks, intros).** Build a message hierarchy instead of slide sections: the one-sentence version, the 30-second version, the 2-minute version — each fully containing the shorter one, so the speaker can stop cleanly at any depth. Time each version by word count. Framing and glossary sections still apply.

### Timing section

Run the measurement script after drafting and again after every user edit:

```bash
python3 <skill-path>/scripts/measure_timing.py notes.md --wpm 130
```

Then write the Timing section from the numbers: per-slide targets, 3–4 clock checkpoints ("slide 9 done by ~6:30"), a **cut-first list** (which Expand blocks or slides collapse to one sentence, in order), and **safe expanders** (the only places to stretch — typically the slides the speaker owns most). If the measured script is far under budget, expand by walking more slide content — never by inventing material; if far over, cut Expand blocks before touching Say lines.

In **natural mode** the measurement is a proxy, not the clock: the speaker improvises around the notes, and improvisation runs *longer* than the written points. Compensate two ways — write key messages as full speakable sentences (so the proxy is honest), and land the measured total well under budget (~85% of the slot), leaving the overrun room improvisation will take.

## Step 3 — Voice pass

Hand the markdown to the user to edit for their voice and domain knowledge. When they return it: preserve their wording everywhere, answer any bracketed questions inline, act on their margin notes, and re-run the timing measurement (their edits change the clock).

For scripted modes, the final text should end up **phrase-per-line**: each line one spoken phrase, broken at natural pause points. If the user hasn't done this themselves, do it as a final formatting pass — it's the single most important delivery-format convention (see `references/delivery-format.md` for why).

## Step 4 — Build the outputs

Ask which outputs the engagement needs (or infer: scripted/backup → all; natural → the condensed outline plus a distribution-copy PDF *of the notes document*; no-slides → usually just the markdown and a pocket-card PDF).

**Slide-advance cues** (when someone else runs the slides): insert one marker line at each advance point, at the exact spot in the script where the advance belongs:

```html
<div class="advance">▶ NEXT SLIDE (7)</div>
```

Number it with the slide being advanced *to* (doubles as a wrong-slide check). Add a Ground rules bullet telling the speaker what to do at a marker (say "next slide, please", or a pre-agreed nod).

**Build the PDFs:**

```bash
python3 <skill-path>/scripts/build_pdfs.py notes.md --outdir . --header "Project · Speaker Script"
```

This produces two files from the one source (requires pandoc + Chrome or weasyprint; the script reports what's missing):

- **Delivery copy** (`*-delivery.pdf`) — 17pt sans, phrase-per-line, text in the top two-thirds of the page (big bottom margin keeps the speaker's eyes up), each `##` section starting on a fresh page (a page turn coincides with a slide advance), large page numbers, advance markers rendered as high-contrast boxes *bound to the preceding paragraph* so they never orphan onto an empty page.
- **Distribution copy** (`*.pdf`) — compact 11.5pt for sharing with the team; advance markers stripped automatically (delivery cues don't belong in the shared version).

**Condensed outline** (for the team, or as the natural-mode deliverable): a separate 1–2 page markdown — per-slide bullets of what will be covered (statements, not speech) plus a short delivery-mechanics section (timing checkpoints, cue conventions, Q&A plan). Build it with `--distribution-only`.

The formatting rationale and conventions (font sizes, line breaks, page handling, pause marks, the two-copies practice) live in `references/delivery-format.md` — read it before deviating from the defaults, and cite it if the user asks why the delivery copy looks the way it does.

## Step 5 — Rehearsal support

Offer, don't push: a timed read-through check (re-measure after final edits and compare to budget), and a one-line pre-meeting checklist (agree the advance cue with the slide operator, print single-sided, slide pages sideways rather than flipping).

## Failure modes to avoid

- Writing eloquent material the speaker can't back up in Q&A. Everything outside their expertise must trace to the slide or the glossary.
- Padding a short script with invented content. Expand only by walking slide content or slowing down; silence while an audience reads a table is fine.
- Overwriting the user's voice edits on a later pass. Their phrasing is the product; yours is the scaffold.
- Formatting the delivery copy like a memo. Dense full-width 11pt paragraphs are for readers, not speakers — if it looks like a document, it will fail at the lectern.
