# Phase 3 source bundle

These are public context assets, not verified incident observations. Runtime
replay and scoring make no provider requests. The original Phase 1/2 fixtures are
unchanged; the two context scenarios are additive.

| Asset | Source and reality status | Interpretation |
|---|---|---|
| `osm-map.xml.gz` | Exact OSM API response, losslessly gzip-compressed; acquisition 2026-09-07 | Real public geography; snapshot completeness/accuracy is unverified |
| `roads.geojson` | Derived road vectors: 910 highway ways from the bounded OSM map response | Local background and competing-way geometry; some complete ways extend beyond the requested box |
| `roads.json` | 20 selected short sections from source node edges; longer edges subdivided by linear interpolation, maximum 110 m | Conservative source/code-reviewed context; no independent human geography review |
| `open-meteo-era5.json` | Exact Open-Meteo ERA5 response for 2025-01-01 through 2025-01-02 | 48 modeled hourly liquid-rain values, all 0 mm; values have not been edited |
| `context_signature.json` | Existing signature-image evidence placed at sourced road midpoints | Synthetic observation placement/time/reports and synthetic 6 mm rainfall; image content remains public-source |
| `context_archive.json` | Same fictional evidence, shifted to January 2025 | Authentic historical weather is attached at reset; observation placement/time remains simulated |

## Attribution and acquisition

- Geography: **© OpenStreetMap contributors**, [ODbL 1.0](https://www.openstreetmap.org/copyright).
  The source and derived geographic database in this directory are distributed
  under ODbL. Raw response and derived vectors are included for inspection and reuse.
  Exact [bounded map request](https://api.openstreetmap.org/api/0.6/map?bbox=31.325,30.045,31.346,30.063).
  No public OSM raster tiles were downloaded or prefetched.
- Weather: **Open-Meteo / Copernicus ECMWF ERA5**, [historical API documentation](https://open-meteo.com/en/docs/historical-weather-api),
  [CC BY 4.0 and API terms](https://open-meteo.com/en/terms). The free API is for
  non-commercial use; this is a local demo, not a municipal deployment licence.
  Requested model is explicitly `era5`, not a changing best-match blend.
  Request coordinates are latitude 30.054, longitude 31.3355. Returned grid center
  is latitude 30.0, longitude 31.25; product resolution is 0.25° (roughly 25 km).
  The application footprint is limited to the study box; it is not a claim of
  street-resolution weather. Elevation returned in the raw response is unused.
- `manifest.json` retains URLs, actual acquisition times, SHA-256 of original
  decompressed response bytes, derived asset hashes, selection policy and demo
  placement. Successful acquisitions used the official OSM API and Open-Meteo.
  Earlier Overpass attempts returned HTTP 406 and a timeout; neither supplied data.

## Fixed adapter semantics

Open-Meteo `rain` is liquid precipitation accumulated over the **preceding hour**.
The timestamp labels the interval end. At 11:15 UTC, the six completed intervals
are labeled 06:00 through 11:00, covering 05:00–11:00 UTC. This is different from
treating timestamps as interval starts. UTC, mm, unique hourly timestamps, finite
nonnegative values, model/grid identity and raw-byte integrity are validated.

Missing/null hours stay null. Wrong units, bad values or malformed responses reject
the context. Missing/corrupt files return explicit unavailable status; there is no
synthetic or zero fallback. The unchanged engine excludes incomplete, stale,
unavailable and out-of-footprint rain. Intermediate totals activate neither R nor
N. Complete dry and wet series feed only the existing N/R hypothesis rules at
strength 0.6; rainfall never changes impact severity or independent captures.

Original historical availability is unknown. The default adapter uses acquisition
as the earliest known availability. Only `context_archive` explicitly applies
`retrospective_demo`, setting effective replay availability to the interval end
while retaining actual acquisition and original provider interval timestamps in
`source`. No values or weather dates are shifted to the September story. This is
neither an as-issued forecast evaluation nor evidence of an actual January event.
Current operator observations do not receive this historical replay context.

Road matching uses the frozen 30 m nearest / 10 m ambiguity / 50 m accuracy gates.
Only same selected short-section membership is enabled; **all cross-section
compatibility lists are empty**. All 910 source highway ways compete with selected
sections during matching. Nearby parallel/crossing/unreviewed ways cause review,
not an inferred junction, bridge connection, or drainage relationship. Selected
classes are residential/living-street → local and primary/secondary/tertiary →
their source class. Service roads are not assumed access-restricted. Manual
operator segments retain unknown class and exposure unless sourced explicitly.

## Reproduce and verify

From repository root, rebuild derived data with no network:

```powershell
.\.venv\Scripts\python.exe -m fixtures.context.build
.\.venv\Scripts\python.exe -m pytest tests/test_context.py -q
```

For an intentional new acquisition of the same two fixed requests:

```powershell
.\.venv\Scripts\python.exe -m backend.fetch_context --output output/context-new
```

The acquisition utility refuses existing output directories, bounds response sizes
and request timeouts, and does not replace the locked bundle. A refreshed OSM
snapshot requires reviewing the sections and regenerating/validating their assets;
it must not be silently substituted beneath existing incident revisions.

The deterministic engine and configuration are not edited by either command.
