# Converge — Phase 4 UI/UX Design Specification

**Status:** Final Visual & UX Refined Specification (Pre-Implementation)  
**Authors:** Control Alt Delete (IMPACTX 2026 Smart Cities)  
**Target Event:** IMPACTX 2026, September 9–10, 2026, ECU Nasr City Campus  
**Target Surfaces:** Responsive PWA with `/` (Entry), `/report` (Mobile-First Signal Capture), and `/operations` (Desktop-First Municipal Intelligence Workbench)  
**Companion Artifacts:** [PRODUCT_ARCHITECTURE_FREEZE.md](../PRODUCT_ARCHITECTURE_FREEZE.md), [BUILD_STATUS.md](../BUILD_STATUS.md), [docs/previews/phase4_preview.html](previews/phase4_preview.html)

---

## Executive Summary

Converge transforms scattered, weak urban observations into explainable candidate incidents and an auditable, prioritized municipal field-inspection queue.

Phase 4 delivers the complete visual, architectural, and responsive frontend experience across two dedicated operational surfaces:
1. **`/report` (Signal Capture):** A mobile-first, friction-free intake channel where citizens and field workers capture what they directly observe (text description, optional photo, detected location, observation timestamp). It avoids bureaucratic categorization, uses clean privacy language, never exposes internal triage formulas, and confirms receipt cleanly.
2. **`/operations` (Incident Workbench):** A desktop-first, map-centric decision workbench for municipal duty engineers. Calibrated for 1280×720 conference-room projectors and 1440×900 desktop monitors, it presents all essential triage metrics on a zero-scroll **Overview** tab, supported by deep **Evidence**, **Hypotheses**, and **Review** tabs, an interactive MapLibre cartographic hero, and a collapsible signature **Convergence Ribbon**.

The visual direction uses subtle surface contrast, generous whitespace, restrained 6–8px corner radii, and high-contrast typography, avoiding generic SaaS borders, dark-mode neon gimmicks, and uncalibrated flood graphics.

---

## 1. Visual Concept & Design Polish

### 1.1 Aesthetic Persona & Tone
The design tone is **Municipal Operational Intelligence**:
- **Credible & Authoritative:** Styled like high-consequence civil infrastructure tools (SCADA, dispatch consoles, geographic intelligence).
- **Subtle Surface Contrast over Heavy Borders:** Replaces heavy gray card outlines with soft tonal elevation (`#FFFFFF` panels on `#F8FAFC` background) and hairline dividers (`#E2E8F0`).
- **Projector-Ready (1280×720 Guarantee):** Built with high tonal contrast so duty engineers and hackathon judges see every critical number, label, and map feature clearly without page scrolling.
- **Truthful & Transparent:** The interface never hides uncertainty, never fabricates AI confidence percentages, and clearly labels the reality status of all data.

### 1.2 Anti-Patterns Explicitly Avoided
- **No Generic SaaS Card-Clutter:** No heavy gray bounding boxes around every label.
- **No Cyberpunk / Dark "Hacker" Theme:** Clean, daylight-optimized light operational palette.
- **No 1990s Bureaucratic Form:** `/report` does not present municipal classification dropdowns.
- **No AI Chatbot Interface:** Spatial-temporal evidence and hypotheses, not conversational dialogue.
- **No Fake Flood Extents:** The $\le 120$ m grouping rule is strictly an evidence-correlation threshold, never rendered as an engineered flood perimeter or hydraulic pooling contour.

---

## 2. Information Architecture & Clean HTML5 Routing

Converge is packaged as **one responsive Progressive Web Application (PWA)** powered by a shared React + Vite frontend and FastAPI backend.

```
                    ┌──────────────────────────────────────────────┐
                    │                      /                       │
                    │         Minimal Clean Entry Gate             │
                    │   "Turn scattered urban signals into         │
                    │    actionable incident intelligence"         │
                    └───────────────┬───────────────┬──────────────┘
                                    │               │
                     [ Report an observation ] [ Open operations ]
                                    │               │
                                    ▼               ▼
        ┌───────────────────────────────┐   ┌─────────────────────────────────────────┐
        │            /report            │   │               /operations               │
        │   Mobile-First Signal Intake  │   │   Desktop-First Incident Workbench      │
        │  ───────────────────────────  │   │  ─────────────────────────────────────  │
        │  • Full device viewport       │   │  • Top Status & Operational Mode Bar    │
        │  • Single-screen capture      │   │  • Left: Inspection / Candidate Queue   │
        │  • Photo + privacy note       │   │  • Center: Cartographic Hero Map (55%) │
        │  • Location detected          │   │  • Right: Tabbed Inspector (Zero-Scroll)│
        │  • Clean signal receipt       │   │  • Bottom: Collapsible Convergence Tray │
        └───────────────────────────────┘   └─────────────────────────────────────────┘
```

### 2.1 Clean HTML5 Routing Specification
- **Clean Path Guarantee:** Routing is locked strictly to standard HTML5 paths:
  - `/` (Entry Gateway)
  - `/report` (Mobile-First Signal Capture)
  - `/operations` (Desktop-First Incident Workbench)
- **NO Hash Routing:** URLs such as `/#/report` or `/#/operations` are strictly prohibited.
- **Deep-Linking Support:** Vite dev server and FastAPI static mounting serve `index.html` on direct URL hits. PWA Service Worker provides offline navigation fallback.

### 2.2 Responsive Surface Priorities
- **Primary Priority 1 (Mobile Surface):** `/report` is designed to fill 100% of the mobile device viewport.
- **Primary Priority 1 (Desktop / Projector Surface):** `/operations` is optimized for 1280×720 (projector) and 1440×900 (workstation).
- **Secondary Responsive Support:** Mobile `/operations` renders a simplified read-only triage list with a direct prompt to open the full workbench on desktop/tablet for map inspection.

---

## 3. Detailed `/operations` Layout & Projector Calibration

The operational workspace occupies 100% of the viewport height with **zero master page scrolling**:

```
+-------------------------------------------------------------------------------------------------------------------+
| [⋈ Converge] Nasr City | [● Live Municipal Mode] | Cairo Clock: 09:31:00 | [Mode: Live / Replay] | [+ Observation]|
+-----------------------+-------------------------------------------------------------+-----------------------------+
| INSPECTION QUEUE      | CARTOGRAPHIC HERO MAP (55% Width)                           | TABBED INCIDENT INSPECTOR   |
| [All | Candidates]    |                                                             | [Overview | Ev | Hypo | Rev]|
|                       | [Road Context: Street 14 (Tertiary)]                        |                             |
| > Candidate B (68)    |                                                             | Street 14 · Tertiary Road   |
|   Street 14           |          [Pin 1: Text (09:14)]                              | Candidate #inc-b82f (Rev 3) |
|   3 Captures · Mod    |                  \                                          |                             |
|   Water + Road Damage |                   \                                         | RISK INDEX     EVIDENCE     |
|                       |        [Pin 2]--[MEDOID B]---[Pin 3: Text (09:31)]          | [ 68 / 100 ]   [●●○ Mod]    |
|   Watch Item A (32)   |         (Photo)                                             | Inspect First  3 Captures   |
|   El-Nasr Road        |        ==================[Street 14 Segment]================|                             |
|   1 Capture · Lim     |                                                             | WHY INSPECT HERE?           |
|                       |  [Guide: "≤120 m all-member correlation threshold —         | 3 independent captures on   |
|   Watch Item C (15)   |          not a flood extent."]                              | Street 14. Water co-occurs  |
|   Abbas El-Akkad      |                                                             | with asphalt damage.        |
|   1 Capture · Lim     |  [Cartographic Legend: Pins, Matched Road, Medoid]          |                             |
|                       |                                                             | STRONGEST HYPOTHESIS        |
|                       |                                                             | > H1: Rainfall ponding (5.1)|
|                       |                                                             |                             |
|                       |                                                             | KEY UNCERTAINTY             |
|                       |                                                             | • Drain inlet unobserved    |
+-----------------------+-------------------------------------------------------------+-----------------------------+
| [⋈ Convergence Ribbon: 3 independent signals + ERA5 context → Candidate #inc-b82f]               [ Expand Ribbon ⌃ ]|
+-------------------------------------------------------------------------------------------------------------------+
```

### 3.1 1280×720 Projector Requirement (Zero Scroll Guarantee)
At 1280×720 resolution, all essential decision data must be visible simultaneously without scrolling:
1. **Incident Queue:** Candidate card with road name, risk index (68), and corroboration badge.
2. **Primary Map:** Centered on Street 14, showing member pins and highlighted road context.
3. **Inspector Overview:** Identity, Risk Index ($68/100$), inspection band (`Inspect First`), Evidence Strength (`Moderate`), independent capture count ($3$), executive summary, strongest hypothesis ($H_1$), and key uncertainty.
4. **Convergence Ribbon:** Sleek 32px collapsed handle at screen bottom preserving maximum vertical map space.

### 3.2 Tabbed Inspector Module Architecture
The inspector replaces long vertical stacking with 4 distinct tabs:

1. **`Overview` (Default, Zero-Scroll):**
   - **Identity:** Road name, incident ID (`#inc-b82f`), revision, and observed condition tags.
   - **Dual Metric Summary:** Side-by-side display of Risk Index ($68/100$, `Inspect First`) and Evidence Strength ($●●○$ `Moderate`, $3$ independent captures).
   - **"Why Inspect Here?":** Concise, deterministic 2-sentence executive summary.
   - **Strongest Hypothesis:** Prominently highlights leading interpretation ($H_1$, $5.10$ pts).
   - **Key Uncertainty:** Highlights critical missing evidence or unobserved components (e.g. drain inlet clearance).
2. **`Evidence` Tab:**
   - Chronological list of admitted evidence cards.
   - Bilingual source quotes (`dir="auto"`), image thumbnails, and exact provenance badges (`AI Extracted`, `Cached AI`, `Human Reviewed`).
3. **`Hypotheses` Tab:**
   - Detailed breakdown of all competing physical interpretations:
     - $H_1$: Persistent rainfall ponding / drainage limitation ($5.10$ pts, Leading).
     - $H_3$: Non-rainfall water source ($1.90$ pts, Alternative).
     - $H_2$: Transient surface runoff ($1.60$ pts, Alternative).
   - Shows rule support contributions and missing discriminators.
4. **`Review & Field Check` Tab:**
   - Interactive Field Inspection Checklist (`[ ] Check drain opening`, `[ ] Measure depth`).
   - Human review status (`Unreviewed / Needs Inspection / Closed`).
   - Inline extraction correction trigger.

### 3.3 Cartographic Visual Hierarchy (Map Hero)
- **Quieter Non-Selected Roads:** Muted light slate/gray (`#CBD5E1`) blending softly into the background (`#F1F5F9`).
- **Strong Selected Road Context:** Bold, high-contrast casing for the matched OSM highway segment (`Street 14` tertiary road cased in `#0F766E` teal on `#FFFFFF` roadbed).
- **Clear Member Observations:** Distinct high-contrast pins for admitted members:
  - Text observation: Teal pin (`#0D9488`).
  - Field image observation: Warm amber pin (`#D97706`).
- **Pairwise Guide Label:** Any displayed spatial correlation line is strictly labeled:
  > **`"≤120 m all-member correlation threshold — not a flood extent."`**
- **Clean Legend:** Minimal floating pill legend with clean icons and zero decorative clutter.

### 3.4 Collapsible Signature Convergence Ribbon
- **Collapsed State (Default on Projector):**
  - Sleek 32px bar at the bottom:  
    `[ ⋈ Convergence Ribbon: 3 independent signals + ERA5 context → Candidate #inc-b82f ]`  
    `[ Expand Ribbon ⌃ ]`
  - Preserves maximum vertical height for the map and inspector.
- **Expanded State (Interactive Exploration):**
  - Slides up to 140px height with a clear `[ Collapse Ribbon ⌄ ]` trigger.
  - Visually presents the multi-signal chronological accretion:
    $$\text{09:14 Text (Arabic)} \longrightarrow \text{09:18 Image (Photo)} \longrightarrow \text{09:31 Text (English)} \longrightarrow \text{ERA5 Rain (6mm)} \longrightarrow \mathbf{\text{Candidate B Formed}}$$
  - In **Replay / Audit Mode**, reveals the quarantined ablation sandbox (`Hide Images`, `Add 10 Duplicates`) and replay step scrubber.

---

## 4. Friendly, User-Centric `/report` Flow

The `/report` screen is engineered for swift citizen and field worker reporting. On real devices, it **fills 100% of the mobile viewport** (the phone frame presentation is strictly an illustrative device in design previews).

```
+------------------------------------------+
|  [⋈ Converge]           [Cairo 09:31]    |
|  SIGNAL CAPTURE                          |
+------------------------------------------+
|                                          |
|  What do you see?                        |
|  +------------------------------------+  |
|  | Water covering half the lane near  |  |
|  | the curb. Pothole hidden under it. |  |
|  | مياه متراكمة في الحارة اليمين       |  |
|  +------------------------------------+  |
|                                          |
|  Add a photo (optional)                  |
|  +------------------------------------+  |
|  |  [ CAMERA ICON ]                   |  |
|  |  Take photo or choose from library |  |
|  +------------------------------------+  |
|  Photo metadata is removed for privacy.  |
|                                          |
|  Location detected                       |
|  [●] Street 14, Nasr City                |
|  [ Change pin on map ]                   |
|                                          |
|  When was this observed?                 |
|  (●) Just now (09:31)                    |
|  ( ) Earlier today [Select time]         |
|                                          |
|  +------------------------------------+  |
|  |       SEND OBSERVATION             |  |
|  +------------------------------------+  |
|  Reports are registered as observational |
|  signals for municipal engineering.      |
+------------------------------------------+
```

### 4.1 Copy & UX Refinements
- **Primary CTA:** Changed from `"Send Observation to Municipal Engine"` $\rightarrow$ **`"Send observation"`**.
- **Friendly Geolocation:** Displays **`"Location detected"`** with friendly street and district name (e.g. `Street 14, Nasr City`). Removed internal debug strings like `"Matched to OSM Highway ±8m"`.
- **User Privacy Language:** Replaced technical jargon (`"Normalized client-side · EXIF scrubbed"`) with clean, citizen-friendly copy:  
  > **`"Photo metadata is removed for privacy."`**
- **Clean Receipt Screen:** Confirms registration with Signal ID (`#sig-4f81c9`), Cairo timestamp, and reassurance. Never leaks internal municipal risk scores or hypotheses.

---

## 5. Heavily Simplified `/` Entry Screen

The entry screen is reduced to pure essentials, eliminating all implementation coordinates, road counts, and debug data:

```
+===================================================================================+
|                                                                                   |
|                                        ⋈                                          |
|                                    CONVERGE                                       |
|                                                                                   |
|                   Turn scattered urban signals into actionable                    |
|                              incident intelligence.                               |
|                                                                                   |
|            +----------------------------+    +----------------------------+       |
|            |   REPORT AN OBSERVATION    |    |      OPEN OPERATIONS       |       |
|            +----------------------------+    +----------------------------+       |
|                                                                                   |
|                     Nasr City Municipal Prototype · IMPACTX 2026                  |
|                                                                                   |
+===================================================================================+
```

- **Removed Clutter:** No bounding box coordinates (`30.045–30.063 N`), no road way counts (`910 ways`), no deterministic engine status badges.
- **Retained Core:**
  1. Converge brand mark `⋈` and name.
  2. Concise value proposition: *"Turn scattered urban signals into actionable incident intelligence."*
  3. Direct primary CTA: `[ Report an observation ]` $\rightarrow$ routes to `/report`.
  4. Direct secondary CTA: `[ Open operations ]` $\rightarrow$ routes to `/operations`.
  5. Discrete project context: `Nasr City Study Prototype · IMPACTX 2026`.
- **Rule:** System diagnostics and data-health monitoring belong exclusively inside `/operations`.

---

## 6. Typography & Offline Bilingual Handling

### 6.1 Font Stacks (100% Offline Bundled)
- **Primary Latin UI Font:** `Inter` (bundled locally in static assets).
- **Primary Arabic Font:** `Noto Sans Arabic` (bundled locally in static assets).
- **CSS Stack Declaration:**
  ```css
  font-family: 'Inter', 'Noto Sans Arabic', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  ```
- **Monospace Stack:**
  ```css
  font-family: 'JetBrains Mono', 'SF Mono', 'Roboto Mono', Consolas, monospace;
  ```

### 6.2 Bidirectional Text Rules (LTR Workbench Stability)
- **Workbench Shell Layout:** Strictly **Left-to-Right (`dir="ltr"`)**.
- **Content-Level RTL:** User-generated Arabic text blocks, street names, and quotes use `dir="auto"` strictly on their individual content containers.
- **Strict Rule:** Displaying an Arabic report **never flips the workbench, queue, tabs, or inspector into RTL**.

---

## 7. Color / Token System

```css
:root {
  /* Brand Foundation */
  --cv-brand-primary:      #0F766E; /* Deep municipal teal */
  --cv-brand-primary-hover:#0D9488; /* Lighter interactive teal */
  --cv-brand-subtle:       #CCFBF1; /* Pale teal tint */
  
  /* Soft Surface Contrast (Replaces heavy borders) */
  --cv-surface-bg:         #F8FAFC; /* Slate-50 canvas */
  --cv-surface-card:       #FFFFFF; /* Pure white elevated panels */
  --cv-surface-sidebar:    #F1F5F9; /* Slate-100 queue background */
  --cv-surface-sunken:     #E2E8F0; /* Soft input fills */
  
  /* Hairline Dividers */
  --cv-border-light:       #E2E8F0; /* Hairline divider */
  --cv-border-medium:      #CBD5E1; /* Input borders */
  --cv-border-strong:      #94A3B8; /* Active indicator boundary */

  /* High-Contrast Operational Text */
  --cv-text-primary:       #0F172A; /* Deep slate, 14:1 contrast */
  --cv-text-secondary:     #475569; /* Slate secondary, 6.5:1 contrast */
  --cv-text-muted:         #64748B; /* Tertiary metadata */
  --cv-text-inverse:       #FFFFFF;

  /* Triage & Severity */
  --cv-risk-high:          #B91C1C; /* Dark red: Inspect First (R >= 65) */
  --cv-risk-high-bg:       #FEE2E2;
  --cv-risk-med:           #B45309; /* Deep amber: Inspect (35 <= R < 65) */
  --cv-risk-med-bg:        #FEF3C7;
  --cv-risk-low:           #475569; /* Slate: Watch Item (R < 35) */
  --cv-risk-low-bg:        #F1F5F9;

  /* Verification & Provenance */
  --cv-verified:           #15803D; /* Forest green: Human verified */
  --cv-verified-bg:        #DCFCE7;
  --cv-uncertain:          #6B21A8; /* Violet: Uncertainty */
  --cv-uncertain-bg:       #F3E8FF;

  /* Map Hierarchy Colors */
  --cv-map-road-quiet:     #CBD5E1; /* Muted non-selected roads */
  --cv-map-road-selected:  #0F766E; /* Bold selected road casing */
  --cv-map-pin-text:       #0D9488; /* Text observation pin */
  --cv-map-pin-image:      #D97706; /* Image observation pin */
  --cv-map-spatial-guide:  #0F766E; /* Pairwise threshold guide */
}
```

---

## 8. Provenance & Risk/Evidence Distinction

### 8.1 Provenance Badge Language
- `AI Extracted` (`#F1F5F9`, `#334155`) — Extracted automatically via hosted LLM rubric.
- `Cached AI` (`#F8FAFC`, `#475569`) — Stored, immutable model response with verified hash.
- `Human Reviewed` (`#DCFCE7`, `#166534`) — Verified or corrected by municipal engineer.
- `Citizen Reported` (`#F0FDF4`, `#15803D`) — Ingested directly via `/report` intake.
- `Public Source` (`#FEF3C7`, `#92400E`) — External open repository.
- `Synthetic Placement` (`#FEF2F2`, `#991B1B`) — Real image at simulated demo time/location.
- `Derived by Engine` (`#F3E8FF`, `#6B21A8`) — Deterministic spatial/temporal calculation.

### 8.2 Distinct Operational Questions
- **Risk Index ($0\text{--}100$):** Answers *"How urgent is inspection?"* Displayed as an integer with band badge (`Inspect First`, `Inspect`, `Watch`). If components are unobserved, rendered as an interval ($52\text{--}83$, provisional).
- **Evidence Strength (`Limited`, `Moderate`, `Strong`):** Answers *"How well corroborated is this incident?"* Displayed as a 3-pip meter. Automated runs cap at `Moderate`; `Strong` strictly requires physical human verification.
- **Zero fake AI confidence percentages.**

---

## 9. PWA & Implementation Roadmap

### 9.1 Service Worker & PWA Manifest
- `name: "Converge — Municipal Incident Intelligence"`
- `short_name: "Converge"`
- `display: "standalone"`
- `theme_color: "#0F766E"`
- Offline caching of vector road geometry, fonts (`Inter`, `Noto Sans Arabic`), and clean HTML5 path fallbacks.

### 9.2 Implementation Order
1. **Phase 4A:** Design system tokens, offline fonts, PWA manifest, clean HTML5 routing with SPA fallback.
2. **Phase 4B:** Full-viewport mobile `/report` signal capture and receipt flow.
3. **Phase 4C:** 1280×720 projector-calibrated `/operations` workbench, MapLibre quiet/selected hierarchy, queue.
4. **Phase 4D:** Tabbed inspector (Overview, Evidence, Hypotheses, Review), collapsible Convergence Ribbon, Replay sandbox.
5. **Phase 4E:** Operational edge states, mobile read-only triage list, final projector QA.

---

## Key Screen Text Wireframes

### Wireframe 1: Simplified Entry Screen (`/`)
```
+===================================================================================+
|                                                                                   |
|                                        ⋈                                          |
|                                    CONVERGE                                       |
|                                                                                   |
|                   Turn scattered urban signals into actionable                    |
|                              incident intelligence.                               |
|                                                                                   |
|            +----------------------------+    +----------------------------+       |
|            |   REPORT AN OBSERVATION    |    |      OPEN OPERATIONS       |       |
|            +----------------------------+    +----------------------------+       |
|                                                                                   |
|                     Nasr City Municipal Prototype · IMPACTX 2026                  |
|                                                                                   |
+===================================================================================+
```

### Wireframe 2: Friendly Signal Capture (`/report`)
```
+===================================================+
| [⋈ Converge]                    [09:31 Cairo]     |
| SIGNAL CAPTURE                                    |
+---------------------------------------------------+
| What do you see?                                  |
| [ Describe water, road condition, blockage...   ] |
| [                                               ] |
|                                                   |
| Add a photo (optional)                            |
| [ + Take photo or choose from library ]           |
| Photo metadata is removed for privacy.            |
|                                                   |
| Location detected                                 |
| [●] Street 14, Nasr City                          |
| [ Change pin on map ]                             |
|                                                   |
| When was this observed?                           |
| (●) Just now (09:31)   ( ) Earlier today          |
|                                                   |
| [ SEND OBSERVATION ]                              |
|                                                   |
| Reports are registered as observational signals   |
| for municipal engineering.                        |
+===================================================+
```

### Wireframe 3: 1280×720 Projector-Calibrated Workbench (`/operations`)
```
+===================================================================================================================+
| [⋈ Converge] Nasr City | [● Live Municipal Mode] | Cairo: 09:31 | [Toggle Replay Mode] | [+ New Observation]     |
+------------------------+-------------------------------------------------------------+----------------------------+
| QUEUE [Candidates (1)] | MAP WORKSPACE (Quieter non-selected roads · Selected bold)  | INSPECTOR [OVERVIEW (Tab)] |
|                        |                                                             | Sector: Street 14 (Cand B) |
| > CANDIDATE B          |   Street 14 Tertiary Road Context (Highlighted)             |                            |
|   Street 14            |          Text Obs (09:14)                                   | RISK: 68/100 Inspect First |
|   Risk: 68/100         |                 \                                           | EVIDENCE: Moderate (●●○)   |
|   3 Captures · Mod     |        [Obs 2]--[MEDOID B]--[Obs 3]                          | 3 Independent Captures     |
|   Water + Road Damage  |         ================[Street 14 Highway Segment]======== |                            |
|                        |        [Guide: "≤120 m all-member correlation threshold —   | WHY INSPECT HERE?          |
|   WATCH ITEMS (2)      |                 not a flood extent."]                       | 3 captures on Street 14.   |
|   - Item A (Risk 32)   |                                                             | Water co-occurs with damage|
|   - Item C (Risk 15)   |   [Legend: ● Member Pin  === Matched Road  [B] Medoid]      |                            |
|                        |                                                             | STRONGEST HYPOTHESIS       |
|                        |                                                             | > H1: Ponding/Drain (5.10) |
|                        |                                                             |                            |
|                        |                                                             | KEY UNCERTAINTY            |
|                        |                                                             | • Drain inlet unobserved   |
+------------------------+-------------------------------------------------------------+----------------------------+
| [⋈ Convergence Ribbon: 3 independent signals + ERA5 context → Candidate #inc-b82f]               [ Expand Ribbon ⌃ ]|
+===================================================================================================================+
```
