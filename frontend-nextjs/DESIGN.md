---
name: SoldierIQ
description: The Intelligence Estimate — a mission-grade operational knowledge system that answers as a cited, graded analytic product.
colors:
  ground: "#0B0F0E"
  panel: "#101514"
  raised: "#161D1B"
  sunken: "#070A09"
  ink: "#E7E6DC"
  ink-strong: "#FBFBF6"
  ink-muted: "#99A08F"
  ink-faint: "#5C6259"
  rule: "#1F2624"
  rule-strong: "#2C3430"
  olive-drab: "#B2AA7D"
  olive-deep: "#837B54"
  signal-red: "#CC4B39"
  supported-green: "#7FA65E"
  warn-amber: "#D6A43C"
  paper: "#E9E3D1"
  paper-shade: "#E0D9C2"
  paper-ink: "#1B1F19"
  paper-muted: "#55584A"
  paper-rule: "#C6BC9F"
  paper-signal: "#B03A2A"
typography:
  display:
    fontFamily: "Saira Condensed, Arial Narrow, ui-sans-serif, sans-serif"
    fontSize: "clamp(3.25rem, 8vw, 6.5rem)"
    fontWeight: 800
    lineHeight: 0.9
    letterSpacing: "-0.015em"
  command:
    fontFamily: "Saira Condensed, Arial Narrow, ui-sans-serif, sans-serif"
    fontSize: "clamp(1.75rem, 3.5vw, 3rem)"
    fontWeight: 700
    lineHeight: 0.98
    letterSpacing: "-0.005em"
  body:
    fontFamily: "Public Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: "normal"
  label:
    fontFamily: "Overpass Mono, ui-monospace, monospace"
    fontSize: "10.5px"
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "0.16em"
  mono:
    fontFamily: "Overpass Mono, ui-monospace, monospace"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.45
    letterSpacing: "normal"
    fontFeature: "tnum 1"
rounded:
  none: "0"
  xs: "2px"
spacing:
  gutter: "40px"
  section-y: "96px"
components:
  button-primary:
    backgroundColor: "{colors.olive-drab}"
    textColor: "#14170D"
    typography: "{typography.command}"
    rounded: "{rounded.none}"
    padding: "0.85rem 1.4rem"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.command}"
    rounded: "{rounded.none}"
    padding: "0.85rem 1.3rem"
  grade-chip:
    backgroundColor: "transparent"
    textColor: "{colors.paper-signal}"
    typography: "{typography.mono}"
    rounded: "{rounded.none}"
    padding: "1px 5px"
---

# Design System: SoldierIQ

> Scope: this file documents the **public / Persuade identity** — the "Intelligence Estimate" world established for the marketing surfaces (landing at `app/page.tsx`, scoped under the `.iqx` class in `app/globals.css`). The authenticated **Operate** surfaces (dashboard) keep their own neutral token set (`:root` / `.dark` in `globals.css`); the older `.ops` "operational console" scope still backs the auth pages and is being superseded by this world.

## Overview

**Creative North Star: "The Intelligence Estimate"**

SoldierIQ answers as a finished all-source intelligence estimate — an assessed answer, a confidence lexicon, and footnoted source-reliability grading. The identity makes that literal: the surface is a dark analytic operations ground on which a single **warm estimate sheet** is worked. Provenance is not a claim on this page, it is the material — a real cited assessment with a reliability ledger the visitor can re-grade in their own hands.

The world deliberately refuses the two ruts this category falls into: the dark-HUD "tactical dashboard" (near-black + neon + fake terminal + crosshair chrome) and the neutral enterprise-AI hero (white, rounded cards, gradient). It is mission-grade without cosplay: authority comes from the analytic-document tradition (numbered assessment, A–F / 1–6 admiralty grading, classification handling, engraved figure captions), not from HUD decoration.

Density is high and confident — monumental condensed display against small monospace data, hairline-ruled ledgers, generous vertical breathing between sections. Nothing glows for effect; the one warm sheet earns all the contrast.

**Key Characteristics:**
- A dark graphite-green operations ground carrying one warm, worked estimate sheet.
- Condensed command display (Saira) + government body (Public Sans) + Highway-Gothic mono (Overpass Mono).
- Square corners, hairline rules, drawn marks — no pills, no soft shadows on dark, no glyph icons.
- Every metric and citation is real data type (tabular mono), never mono-as-costume.
- One authored interaction — the reliability scrub — carries the thesis; motion elsewhere is restrained.

## Colors

A near-monochrome graphite-green field with a single olive-drab voice, a signal-red reserved for classification and provenance marks, and one warm manila plate that owns the proof surface.

### Primary
- **Olive Drab** (`#B2AA7D`): the brand voice — primary buttons, active/emphasis words in headlines, figure and label accents, focus. The system's one saturated color; it stays sparse.

### Secondary
- **Signal Red** (`#CC4B39`): classification and alarm only — the classification-strip dot, citation ticks, provenance ties in the graph, and the `INSUFFICIENT` confidence state. Never decorative.
- **Supported Green** (`#7FA65E`) / **Warn Amber** (`#D6A43C`): operational status (live dot, high-confidence, caution). Small, functional.

### Neutral (dark ground)
- **Ground** (`#0B0F0E`): the operations surface — a solid, unornamented field.
- **Panel / Raised / Sunken** (`#101514` / `#161D1B` / `#070A09`): flat layered surfaces — panels, cards, and the classification banners.
- **Ink** (`#E7E6DC`), **Ink-Strong** (`#FBFBF6`), **Ink-Muted** (`#99A08F`), **Ink-Faint** (`#5C6259`): body, headline, secondary, and disabled text — all tinted warm, never pure gray.
- **Rule / Rule-Strong** (`#1F2624` / `#2C3430`): hairline dividers and panel borders.

### Tertiary (the estimate sheet)
- **Paper** (`#E9E3D1`) with **Paper-Ink** (`#1B1F19`), **Paper-Muted** (`#55584A`), **Paper-Rule** (`#C6BC9F`), **Paper-Signal** (`#B03A2A`): the warm manila document world. The only light surface; it is where provenance is shown, so it is deliberately the visual focus.

### Named Rules
**The One Voice Rule.** Olive drab is the only saturated brand color and stays under ~10% of any screen; its rarity is the authority. Signal red is rarer still and means classification, citation, or alarm — never emphasis.

**The Warm Sheet Rule.** There is exactly one light surface — the estimate sheet. It earns focus by contrast; do not add second and third paper panels or the proof loses its weight.

## Typography

**Display Font:** Saira Condensed (fallback Arial Narrow) — a technical, aeronautical condensed grotesk for command headlines, always uppercase.
**Body Font:** Public Sans (fallback system sans) — the US Web Design System face; a plain, credible government-document voice.
**Label / Mono Font:** Overpass Mono (fallback ui-monospace) — Highway-Gothic-derived; carries all data, citations, grades, coordinates, and small tracked labels.

**Character:** Compression and authority up top, plain officialdom in the running text, and instrument-grade monospace for every number. The pairing reads as a serious analytic publication, not a consumer app.

### Hierarchy
- **Display** (Saira Condensed 800, `clamp(3.25rem, 8vw, 6.5rem)`, lh 0.9, uppercase): the hero and section headlines; monumental, tight.
- **Command** (Saira Condensed 700, ~1.75–3rem, lh 0.98, uppercase): capability names, sheet titles, masthead.
- **Body** (Public Sans 400/500, 15–16.5px, lh ~1.65): leads and paragraphs; measure held to ~52–54ch.
- **Label** (Overpass Mono 600, 10.5px, 0.16em, uppercase): section labels, figure captions, status readouts.
- **Data / Mono** (Overpass Mono, 11–15px, tabular): grades, citations `[n]`, counters, DTG, coordinates.

### Named Rules
**The Data-Is-Mono Rule.** Monospace appears only on real measurement — grades, citations, counts, timestamps, coordinates. It is never a "technical" costume on prose.

**The Tabular Rule.** Every number that can change or align (counters, grades, readouts) uses tabular figures (`tnum`) so instruments don't jitter.

## Layout

A 12-column grid inside a `max-w-[1320px]` container with `24px → 40px` gutters. Sections are separated by full-width `rule-strong` borders and a generous vertical rhythm (`64–112px` top/bottom), with more space above a heading than below it. The composition is asymmetric: a monumental headline column paired with a taller working panel (hero sheet, graph figure). A slim classification strip tops the page; a sticky, backdrop-blurred masthead and an operational status strip sit beneath it. On mobile everything stacks to one column; the estimate sheet and figures reflow intact.

## Elevation & Depth

The dark ground is **flat** — depth comes from tonal layering (ground → panel → raised) and hairline rules, never from shadows on dark surfaces. The single exception is the warm estimate sheet, which casts a real drop shadow to read as a physical document lifted onto the operations table.

### Shadow Vocabulary
- **Sheet lift** (`box-shadow: 0 22px 50px -18px rgba(0,0,0,0.7), 0 6px 18px -8px rgba(0,0,0,0.5)`): only on the manila estimate sheet.
- **Button hover glow** (`box-shadow: 0 6px 22px -6px rgba(178,170,125,0.14)`): a low olive glow under the primary action on hover.

### Named Rules
**The Flat-Ground Rule.** Dark surfaces never carry shadows; they layer by tone and hairline. Shadow is reserved for the one paper object.

## Shapes

Square by default. Corners are `0` on structural surfaces and at most `2px` (`rounded.xs`) on small controls — no pills, no rounded cards. The recurring geometry is the **registration tick**: a 1px olive corner bracket (`iq-reg`) drawn on the top-left and bottom-right of key panels, echoing a plate/estimate reference mark. Dividers are always 1px hairlines; borders never exceed 1px.

## Components

### Buttons
- **Shape:** square (`0` radius).
- **Primary** (`iq-btn`): olive-drab fill (`#B2AA7D`) on near-black text (`#14170D`), Saira Condensed uppercase, `0.85rem 1.4rem`.
- **Hover / Focus:** lighten to `#C6BE8F` with a low olive glow; active translates down 1px.
- **Ghost** (`iq-btn-ghost`): transparent with a `rule-strong` border and ink text; border and text shift to olive on hover.

### Chips
- **Style:** data tags (`iq-mono`, 11px) with a 1px `rule-strong` border on `panel`, square. Used for capability bullets.
- **Grade chip:** admiralty code (e.g. `A2`), 1px border in the reliability color — green (A/B), amber (C/D), signal (E/F).

### Cards / Containers
- **Panel** (`iq-panel`): `panel` background, 1px `rule` border, square, `24–32px` padding, usually with `iq-reg` corner ticks. **Raised** (`iq-raised`) is one tone lighter with a stronger border.
- **Shadow Strategy:** none on dark (see Elevation).

### Inputs / Fields
- **Reliability scrub** (`iq-range`): a bare 2px track with a 3px signal-red vertical thumb — reads as a plotting slider, not an OS control. Focus shows a 2px signal outline.

### Navigation
- **Masthead:** drawn reticle mark + "SoldierIQ" in command type + a mono system label; sticky with an 80% ground backdrop-blur. Links are mono labels; the primary nav action is the olive button. Active/hover shifts links to olive.

### Signature Component — The Estimate Sheet
The warm manila document (`iq-paper`): a header (title + ref + DTG + sources-in-scope), a mono requirement line, a cited assessment where each sentence carries superscript `[n]` ticks, the reliability scrub with four live readouts (retained / mean grade / claims held / confidence), and a source-reliability ledger. The scrub sets a minimum source reliability (F→A); sources below it dim, the assessment sentences that rest on them strike through, and confidence recomputes (`SUBSTANTIATED → PARTIAL → THIN → INSUFFICIENT`). It is the page's thesis made operable.

## Do's and Don'ts

### Do:
- **Do** keep the ground flat and layer by tone + 1px hairlines; reserve shadow for the one paper sheet.
- **Do** render every metric, grade, citation, and timestamp in Overpass Mono with tabular figures.
- **Do** let headlines stand alone; use figure captions (`Fig. N —`) only on an actual figure.
- **Do** keep olive drab sparse (≤10%) and signal red rarer still (classification / citation / alarm only).
- **Do** label all demonstration data synthetic ("Sanitised for preview" / "Demonstration data is synthetic").

### Don't:
- **Don't** add eyebrows/kickers above headings, decorative section numbers on non-sequential items, or glyph/emoji icons (marks are drawn SVG or the `iq-dot`).
- **Don't** introduce a second light/paper panel — one estimate sheet only.
- **Don't** use pills, rounded cards, gradient text, or HUD/terminal chrome; this world refuses both the tactical-dashboard and enterprise-SaaS ruts.
- **Don't** invent customers, benchmarks, pricing, or deployment claims.
