# Delivery-format conventions for speech scripts

What professional speechwriters and teleprompter practice converge on, and why the delivery copy is formatted the way it is. Consult before deviating from the defaults in `assets/delivery.css`.

## The governing idea

A delivery script is optimized for the **eye-to-audience round trip**: the speaker looks down, grabs a complete thought in one glance, and delivers it while looking at the audience. Every convention below serves that loop. A document formatted for *readers* (dense paragraphs, small type, full-page text) fails at a lectern even when the words are perfect.

## Conventions

**Phrase-per-line.** Break lines at the ends of natural spoken phrases, never mid-thought — one deliverable unit per glance. This is the single most important convention; it's standard manuscript style among professional speechwriters. Aim for lines a speaker can hold in working memory (roughly 15–20 words max, usually fewer).

**Large mixed-case type.** 14pt minimum; 16–20pt common for lectern scripts (the skill's default is 17pt). Sans-serif (Helvetica/Arial) tests slightly better for scripts. Mixed case, never all caps — caps are markedly harder to read in passages (teleprompters are the historical exception, and these are paper scripts).

**Functional white space.** 1.5–2.0 line spacing; short paragraphs (≤2 sentences); extra vertical space between thought groups — the gap itself cues a pause and a topic shift. Crowded pages are the main cause of losing one's place.

**Top two-thirds of the page only.** A 3–4 inch bottom margin keeps the eyes — and visibly, the chin — up. (Skill default: 3.3in bottom margin.)

**Page breaks at logical pauses.** Never split a sentence or thought across pages. The skill goes further: each slide's section starts on a fresh page, so a page turn always coincides with a slide advance — which doubles as a pacing check.

**Large page numbers, top right.** A dropped stack reorders in seconds. Numbers must be legible at a glance.

**Sparse, visually distinct cues.** Bold key words as memory anchors (not vocal-emphasis marks). Ellipses or `//` for pauses (`//` short breath, `///` two beats). Stage directions in italics/brackets only where essential — e.g. `[*pause 3–5s — let them read the table*]`. Avoid presumptuous directions like "(applause)". Phonetic spellings in parentheses for hard-to-pronounce words.

**Slide-advance cues.** When someone else runs the slides, print an unmissable marker at each advance point (`▶ NEXT SLIDE (n)`), numbered with the slide being advanced *to* so it doubles as a wrong-slide check. Bind the marker to the preceding paragraph so page breaks never strand it alone (build_pdfs.py does this automatically). Agree the spoken/gestured cue with the operator before the session.

**Two copies is standard practice.** A large-type delivery copy for the podium, and a compact ~12pt distribution copy with delivery cues stripped for sharing. Never share the cue-laden copy; never present from the compact one.

**Pace math.** Conversational presenting pace is ~120–135 wpm (teleprompter guidance says 125–150). Words ÷ wpm = minutes; add ~5s per slide for transitions plus instructed pauses. Running short is recoverable (slow down, pause on dense tables); running over is not — so scripts should measure *under* budget with a cut-first list, not at budget.

**Print handling.** Single-sided; card stock if available; slide pages sideways across the lectern rather than flipping them.

## Sources

- Rob Cottingham (speechwriter), "A guide to formatting speaking notes" — robcottingham.ca/2015/09/a-guide-to-formatting-speaking-notes/
- Buckley School of Public Speaking, "How to format a speech text" — buckleyschool.com/magazine/articles/how-to-format-a-speech-text/
- Speak Up For Success, "10 simple ways to make your speech easy to read" — speakupforsuccess.com/reading-your-speech/
- Pro Rhetoric, "In the fight for best speech-script font… it's Arial" — prorhetoric.com/in-the-fight-for-best-speech-script-font-its-arial-by-an-arm/
- Teleprompter.com, "Teleprompter script format for easy reading"; SyncedCue, "How to write a teleprompter script"; Moflow, "Formatting a speech for smooth delivery: 12 steps"
