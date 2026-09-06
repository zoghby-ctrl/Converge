# Phase 1 implementation decisions

The architecture freeze is the product source of truth. These are the smallest
interpretations needed to implement its structured-input slice, not a new scope.

- **No extraction or provider setup.** `.env.example` uses the explicit section C
  model defaults and an empty API key. This resolves the request's earlier
  "empty values only" sentence in favor of its exact later environment contract.
  No runtime reads these variables yet; no API key was requested or used.
- **Structured ingestion** uses the six requested routes only. A custom reviewed
  synthetic `Dataset` may be passed on `POST /api/v1/demo/replay` with `action=reset`.
  No generic observation ingestion or editing API was added. The stored fixture
  contains the replay schedule; only available observations are returned to the
  client or passed into correlation. One dedicated demo dataset is active at a time.
- **Geography:** three bundled synthetic segments inside the Nasr City study
  extent make the engine demonstrable without unreviewed geographic claims.
  The map explicitly says schematic/simulated. They are not OSM or actual surveyed
  roads. Phase 2 should replace them with sourced, reviewed local vectors. Reviewed
  pins supply road IDs; nearest-segment assignment is deferred until real geometry.
- **Images:** image-family fixture annotations have no underlying photo in this
  phase. The UI discloses this. They exercise the same local admission/fusion rules
  that a future validated image extraction would use. Exact image hashes and file
  references are supported by the contract; there is no image upload/decoder.
- **Duplicate policy:** normalized exact text and exact image hashes collapse
  within this demo dataset even with different claimed capture IDs. This is the
  conservative Phase 1 implementation of the user's explicit exact-copy invariant.
  It can undercount independently documented identical generic statements. A later
  reviewer override should implement the freeze's independent-author exception.
  Earliest received canonical content owns extracted facts; copies cannot refresh
  age, add facts, or improve quality. All originals and copies remain in the audit.
  Copy records claiming locations/times outside the capture's normal membership
  bounds quarantine the capture. Near-duplicate detection is deferred.
- **Same-time contradiction:** opposing admitted values within 30 minutes of the
  latest observation of a feature are a conflict. A later observation more than
  30 minutes away supersedes earlier values for current scoring. The freeze does
  not specify this tolerance, so it is explicit in versioned configuration.
  Features are compared within the bounded incident, conservatively treating it
  as one local assessment area. Distinct parts of a road may need finer field review.
- **Persistence:** two independent water captures 30–under 120 minutes apart set
  duration severity to 0.5; 120–360 minutes set it to 1 and activate hypothesis P.
  Intervening admitted negative evidence blocks the series. Reported duration
  alone remains a claim. Only an explicit field-reviewed transient/resolved
  annotation can set duration to 0; a later ordinary dry observation cannot.
- **Obstruction:** a generic obstruction tag can prioritize human review, but does
  not invent water- or road-specific severity. That severity must be annotated in
  the corresponding component. A material generic obstruction conflict makes both
  water/road risk components unknown because its physical attribution is unresolved.
- **Weather:** one complete six-hour vector ending at the most recent completed
  hour, available by the analysis clock and covering every member, receives 0.6
  contextual strength. Missing hours, an old interval, or an invalid footprint
  mean unknown. Intermediate rain gives neither R nor N. Synthetic rain is always
  labeled; it changes interpretation, never impact severity or witness count.
- **Tie behavior:** hypotheses within one point of the top share the leading set;
  all pairwise near-ties, including alternatives, are exposed separately. No water,
  nonpositive maximum, or W-only evidence causes abstention. Every rule contribution
  names its evidence/context IDs. Unknown contributions are omitted from hypothesis
  support; risk traces show lower-bound contributions and retain full upper bounds.
- **Identity/revisions:** greatest capture-group Jaccard overlap >=0.5 is matched
  one-to-one. Human state carries only across identical membership sets; regrouping
  lineage remains explicit. Inactive snapshots remain addressable by ID with
  `active=false`; the default queue contains active results. Reset deliberately
  clears only the dedicated demo database and its revision history.
- **Persistence layout:** seven SQLite tables, foreign keys, indexes, serialized
  writes and atomic step commits. Capture groups, weather context, results and
  provenance use validated JSON within the required tables. Database files live in
  `%LOCALAPPDATA%\Converge\runtime`, outside OneDrive. File images are deferred.
- **Runtime:** Python 3.11.16 was installed project-locally under ignored `.runtime`
  using a project-local `uv` tool after a system-installer command was rejected.
  No system Python/PATH change was needed. Tested Node is 24.18.0. Backend versions
  were pinned after passing smoke tests; the compatible FastAPI/Starlette/AnyIO
  set avoids deprecation warnings observed with the initially resolved releases.
- **MapLibre 6 worker packaging:** Vite's `?worker&url` builds the worker and its
  transitive shared module locally. A plain URL import left a shared-module 404,
  found during visual QA and fixed. No remote glyph, tile, style or icon server is
  referenced. System fonts render labels. A 120 m ring is labeled as a reference,
  not an inferred flood boundary; every-member distance still controls grouping.

All checks use development fixtures. No held-out extraction accuracy, municipal
performance, cost savings or incidents prevented are claimed.
