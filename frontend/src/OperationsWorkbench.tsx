import { scenarioLabel, reviewerLabel, roadLabel } from './display'
import React, { useEffect, useRef, useState, useCallback } from 'react'
import * as maplibregl from 'maplibre-gl'
import type { GeoJSONSource } from 'maplibre-gl'
import type { Feature } from 'geojson'
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { Comparison, Contribution, Incident, Replay, Signal } from './types'
import { navigate } from './router'
import {
  ReviewForm,
  ImageReviewForm,
  ImageResult,
  isImageJob,
  type Job,
  conditions,
  type Revision
} from './ObservationPanel'

maplibregl.setWorkerUrl(mapWorkerUrl)

const empty: Replay = {
  dataset_id: null,
  incidents: [],
  signals: [],
  roads: [],
  step: 0,
  total_steps: 0,
  clock: null,
  mode: 'manual_structured',
  excluded: []
}

const human = (s: string) => s.replaceAll('_', ' ')
const time = (s: string | null) => s ? new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Africa/Cairo',
  hour: '2-digit',
  minute: '2-digit'
}).format(new Date(s)) : '—'

async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch('/api/v1/' + path, body ? {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  } : undefined)
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(`Request failed (${response.status}): ${detail}`)
  }
  return response.json()
}

function Trace({ items }: { items: Contribution[] }) {
  return (
    <ul className="trace">
      {items.map(c => (
        <li key={c.rule_id}>
          <code>{c.rule_id}</code>
          <span>{c.weight} × {c.strength.toFixed(3)} = {c.points.toFixed(2)} pts</span>
          <small>{c.evidence_ids.join(', ') || 'Lower bound 0, full weighted range retained.'}</small>
        </li>
      ))}
    </ul>
  )
}

function MapPanel({
  data,
  incidents,
  signals,
  selected,
  onSelect
}: {
  data: Replay
  incidents: Incident[]
  signals: Signal[]
  selected: string | null
  onSelect: (id: string) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const markers = useRef<maplibregl.Marker[]>([])
  const boundsKey = useRef('')
  const [loaded, setLoaded] = useState(false)
  const [mapError, setMapError] = useState('')
  const [rendered, setRendered] = useState(false)
  const selectRef = useRef(onSelect)
  selectRef.current = onSelect

  useEffect(() => {
    if (!container.current) return
    try {
      const m = new maplibregl.Map({
        container: container.current,
        center: [31.336, 30.054],
        zoom: 15.3,
        attributionControl: false,
        style: {
          version: 8,
          sources: {},
          layers: [{
            id: 'background',
            type: 'background',
            paint: { 'background-color': '#EAEFEA' }
          }]
        }
      })
      map.current = m
      m.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')

      m.on('load', () => {
        // Base sources
        for (const name of ['roads', 'selected-road', 'observations', 'incidents']) {
          m.addSource(name, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
        }

        // Quiet background road network (soft contrast)
        m.addLayer({
          id: 'roads',
          type: 'line',
          source: 'roads',
          paint: { 'line-color': '#c0ccc5', 'line-width': 8 }
        })
        m.addLayer({
          id: 'road-center',
          type: 'line',
          source: 'roads',
          paint: { 'line-color': '#fcfdfb', 'line-width': 4 }
        })

        // Selected Road highlight: bold #0F766E casing with soft teal core
        m.addLayer({
          id: 'selected-road-casing',
          type: 'line',
          source: 'selected-road',
          paint: { 'line-color': '#0F766E', 'line-width': 10, 'line-opacity': 0.85 }
        })
        m.addLayer({
          id: 'selected-road-inner',
          type: 'line',
          source: 'selected-road',
          paint: { 'line-color': '#CCFBF1', 'line-width': 4 }
        })

        // Member observation pins (Color by family: #438f98 text, #a06d27 image)
        m.addLayer({
          id: 'observations',
          type: 'circle',
          source: 'observations',
          paint: {
            'circle-radius': 5,
            'circle-color': ['match', ['get', 'family'], 'image', '#a06d27', '#438f98'],
            'circle-stroke-width': 2,
            'circle-stroke-color': '#ffffff'
          }
        })

        // Incident markers (candidate #b85c35, watch #5c7772)
        m.addLayer({
          id: 'incidents',
          type: 'circle',
          source: 'incidents',
          paint: {
            'circle-radius': ['case', ['get', 'selected'], 16, 11],
            'circle-opacity': 0.9,
            'circle-color': ['match', ['get', 'status'], 'candidate', '#b85c35', '#5c7772'],
            'circle-stroke-width': ['case', ['get', 'selected'], 3.5, 2],
            'circle-stroke-color': '#ffffff'
          }
        })

        m.on('click', 'incidents', e => {
          const id = e.features?.[0]?.properties?.id
          if (id) selectRef.current(id)
        })
        m.on('mouseenter', 'incidents', () => { m.getCanvas().style.cursor = 'pointer' })
        m.on('mouseleave', 'incidents', () => { m.getCanvas().style.cursor = '' })

        setLoaded(true)
      })

      m.on('error', e => setMapError(e.error.message))
      m.on('idle', () => {
        if (m.getLayer('roads')) setRendered(m.queryRenderedFeatures({ layers: ['roads'] }).length > 0)
      })

      const observer = new ResizeObserver(() => m.resize())
      observer.observe(container.current)
      return () => {
        observer.disconnect()
        m.remove()
        map.current = null
      }
    } catch (e) {
      setMapError(String(e))
    }
  }, [])

  useEffect(() => {
    const m = map.current
    if (!m || !loaded) return

    const set = (name: string, features: Feature[]) => {
      const src = m.getSource(name) as GeoJSONSource | undefined
      if (src) src.setData({ type: 'FeatureCollection', features })
    }

    // Roads GeoJSON
    const roadFeatures: Feature[] = (data.geography?.features as Feature[]) ??
      data.roads.map(r => ({
        type: 'Feature',
        properties: { name: r.name, id: r.road_context_id },
        geometry: { type: 'LineString', coordinates: r.coordinates }
      }))
    set('roads', roadFeatures)

    // Highlighted selected road
    const chosen = incidents.find(i => i.incident_id === selected)
    if (chosen) {
      const matchingRoadFeatures = roadFeatures.filter(f => {
        const name = (f.properties?.name || '').toString().toLowerCase()
        const target = chosen.road_name.toLowerCase()
        return name && (target.includes(name) || name.includes(target.split(' · ')[0]))
      })
      set('selected-road', matchingRoadFeatures)
    } else {
      set('selected-road', [])
    }

    // Observation points
    set('observations', signals.map(s => ({
      type: 'Feature',
      properties: { family: s.source_family, signal_id: s.signal_id },
      geometry: { type: 'Point', coordinates: [s.lon, s.lat] }
    })))

    // Incident markers
    set('incidents', incidents.map(i => ({
      type: 'Feature',
      properties: {
        id: i.incident_id,
        selected: i.incident_id === selected,
        status: i.status
      },
      geometry: { type: 'Point', coordinates: [i.lon, i.lat] }
    })))

    // Text labels above pins
    markers.current.forEach(marker => marker.remove())
    markers.current = incidents.map(i => {
      const label = document.createElement('button')
      label.className = 'map-label'
      label.textContent = roadLabel(i.road_name).split(' · ')[0]
      label.setAttribute('aria-label', `Select map ${label.textContent}`)
      label.onclick = () => selectRef.current(i.incident_id)
      return new maplibregl.Marker({ element: label, offset: [0, -28] })
        .setLngLat([i.lon, i.lat])
        .addTo(m)
    })

    // Bounds fit
    const locations = [...new Set(signals.map(s => `${s.lon},${s.lat}`))].sort()
    const key = locations.join(';')
    if (key && key !== boundsKey.current) {
      boundsKey.current = key
      const bounds = new maplibregl.LngLatBounds()
      signals.forEach(s => bounds.extend([s.lon, s.lat]))
      m.fitBounds(bounds, { padding: { top: 120, bottom: 80, left: 60, right: 60 }, maxZoom: 16, duration: 0 })
    }
  }, [data.roads, data.geography, incidents, signals, selected, loaded])

  return (
    <section className="ops-col-map" aria-label="Nasr City Cartographic Hero Map">
      <div ref={container} className="maplibre-map-container" />

      {/* Top overlay metadata */}
      <div className="map-overlay-caption">
        <b>Nasr City Study Extent</b>
        <span>{data.context_notice ? 'Real OSM geography · synthetic placement' : data.mode.startsWith('operator_') ? 'Operator coordinates · road context may be unverified' : 'Simulated road context · schematic road segments'}</span>
        {data.roads.some(r => r.source?.provider === 'OpenStreetMap') && (
          <small><a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap contributors · ODbL</a></small>
        )}
      </div>

      {/* Explicit spatial threshold guide (Constraint 1 & 4: never a circular flood footprint!) */}
      <div className="map-spatial-guide-badge" role="note">
        <span>ℹ</span>
        <span>≤120 m all-member correlation threshold — not a flood extent.</span>
      </div>

      {/* Legend */}
      <div className="map-overlay-legend">
        <div className="legend-item">
          <span className="legend-dot" style={{ background: '#b85c35' }} />
          <span>Candidate incident</span>
        </div>
        <div className="legend-item">
          <span className="legend-dot" style={{ background: '#5c7772' }} />
          <span>Watch item</span>
        </div>
        <div className="legend-item">
          <span className="legend-dot" style={{ background: '#438f98' }} />
          <span>Text observation</span>
        </div>
        <div className="legend-item">
          <span className="legend-dot" style={{ background: '#a06d27' }} />
          <span>Image observation</span>
        </div>
        <small style={{ color: 'var(--cv-text-muted)', marginTop: 2 }}>
          Markers show observation and incident locations.
        </small>
      </div>

      {mapError && (
        <p className="map-error" role="alert">Map unavailable: {mapError}. Use queue to select locations.</p>
      )}
    </section>
  )
}

function TabbedInspector({
  incident: i,
  signals,
  onInspectSignal,
  onReviewSaved
}: {
  incident: Incident
  signals: Signal[]
  onInspectSignal: (s: Signal) => void
  onReviewSaved?: () => void
}) {
  const [tab, setTab] = useState<'overview' | 'evidence' | 'hypotheses' | 'review'>('overview')
  const [selectedSid, setSelectedSid] = useState<string>(i.signal_ids[0] ?? '')
  const [job, setJob] = useState<Job | null>(null)
  const [jobLoading, setJobLoading] = useState(false)
  const [editing, setEditing] = useState(false)

  useEffect(() => {
    if (!i.signal_ids.includes(selectedSid)) {
      setSelectedSid(i.signal_ids[0] ?? '')
      setEditing(false)
    }
  }, [i.incident_id, i.signal_ids, selectedSid])

  useEffect(() => {
    if (!selectedSid) {
      setJob(null)
      return
    }
    let canceled = false
    setJobLoading(true)
    api<Job>(`signals/${selectedSid}/processing`)
      .then(res => {
        if (!canceled) {
          setJob(res)
          setJobLoading(false)
        }
      })
      .catch(() => {
        if (!canceled) {
          setJob(null)
          setJobLoading(false)
        }
      })
    return () => { canceled = true }
  }, [selectedSid])

  const leadingHypothesis = i.hypotheses.reduce((prev, curr) =>
    (curr.support_points > prev.support_points ? curr : prev), i.hypotheses[0] || null)

  const filledPips = Math.min(4, Math.max(1, i.independent_capture_count))
  const riskTone = i.status === 'watch' || i.risk.risk_band.toLowerCase().includes('watch')
    ? 'watch'
    : i.risk.risk_band.toLowerCase().includes('inspect first')
    ? 'high'
    : 'medium'
  const primaryAction = i.trace.inspection_checks[0]?.text

  return (
    <aside className="ops-col-inspector" aria-label="Incident Inspector">
      {/* Tab Navigation */}
      <nav className="inspector-tab-bar" aria-label="Inspector Views">
        <button
          className={`inspector-tab-btn ${tab === 'overview' ? 'active' : ''}`}
          onClick={() => setTab('overview')}
        >
          Overview
        </button>
        <button
          className={`inspector-tab-btn ${tab === 'evidence' ? 'active' : ''}`}
          onClick={() => setTab('evidence')}
        >
          Evidence ({i.trace.member_evidence.length})
        </button>
        <button
          className={`inspector-tab-btn ${tab === 'hypotheses' ? 'active' : ''}`}
          onClick={() => setTab('hypotheses')}
        >
          Hypotheses ({i.hypotheses.length})
        </button>
        <button
          className={`inspector-tab-btn ${tab === 'review' ? 'active' : ''}`}
          onClick={() => setTab('review')}
        >
          Review
        </button>
      </nav>

      <div className="inspector-body">
        {/* ================= TAB 1: OVERVIEW (Fits 640px zero-scroll) ================= */}
        {tab === 'overview' && (
          <div className="tab-content">
            <div className="inspector-eyebrow">
              {i.status === 'candidate' ? 'Candidate incident' : 'Watch item'} · Revision {i.revision}
            </div>
            <h2 className="inspector-title">{roadLabel(i.road_name)}</h2>
            <div className="incident-type-line">
              <span>Incident type</span>
              <strong>{i.tag}</strong>
            </div>

            {/* Dual Metric Module */}
            <div className="dual-metric-panel">
              <div className={`metric-card risk-tone-${riskTone}`}>
                <span className="metric-header">Risk priority</span>
                <div className="metric-score">
                  {i.risk.display} <small>/100</small>
                </div>
                <span className="metric-band-pill">
                  {i.risk.risk_band}
                  {i.risk.provisional && i.risk.risk_band !== 'provisional' ? ' · provisional' : ''}
                </span>
                <small className="metric-footnote">
                  Inspection triage · not a probability
                </small>
              </div>

              <div className="metric-card">
                <span className="metric-header">Evidence Strength</span>
                <div className="corroboration-label">{i.evidence_strength}</div>
                <div className="corroboration-pips" title={`${i.independent_capture_count} independent captures`}>
                  {[1, 2, 3, 4].map(idx => (
                    <span
                      key={idx}
                      className={`corroboration-pip ${idx <= filledPips ? 'filled' : ''}`}
                    />
                  ))}
                </div>
                <small style={{ fontSize: '10px', color: 'var(--cv-text-secondary)' }}>
                  {i.independent_capture_count} independent capture{i.independent_capture_count === 1 ? '' : 's'} across {i.signal_ids.length} record{i.signal_ids.length === 1 ? '' : 's'}
                </small>
                <small className="metric-footnote">Corroboration · not severity</small>
              </div>
            </div>

            {primaryAction && (
              <section className="recommended-action-card" aria-label="Recommended next action">
                <span>Recommended next action</span>
                <strong>{primaryAction}</strong>
                <small>Municipal field check · confirm physical cause before intervention.</small>
              </section>
            )}

            {/* Why Inspect Here? */}
            <div className="overview-summary-box">
              {i.status === 'candidate' ? (
                <><strong>Why these observations converge:</strong> Maximum pair distance is {i.max_pair_distance_m.toFixed(1)} m across {i.signal_ids.length} records.</>
              ) : (
                <><strong>Current correlation basis:</strong> {i.independent_capture_count} independent capture{i.independent_capture_count === 1 ? '' : 's'} across {i.signal_ids.length} record{i.signal_ids.length === 1 ? '' : 's'}; the current engine result remains a watch item.</>
              )}
              <details style={{ fontSize: '10px', marginTop: 4 }}><summary>Grouping rule</summary><code>{i.trace.formation_rule}</code></details>
            </div>

            {/* Strongest Hypothesis */}
            {leadingHypothesis && (
              <div className="overview-item-card leading">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                  <span style={{ fontSize: '9px', fontWeight: 700, textTransform: 'uppercase', color: 'var(--cv-brand-dark)' }}>
                    Leading working explanation ({leadingHypothesis.hypothesis_id})
                  </span>
                  <strong style={{ fontFamily: 'var(--font-mono)', color: 'var(--cv-brand-dark)', fontSize: '11px' }}>
                    {leadingHypothesis.support_points.toFixed(1)} support pts
                  </strong>
                </div>
                <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--cv-text-primary)' }}>
                  {leadingHypothesis.title}
                </div>
                <small style={{ fontSize: '10px', color: 'var(--cv-text-secondary)' }}>
                  Not a diagnosis · {leadingHypothesis.tied_or_leading} · Evidence gap: {leadingHypothesis.missing_discriminators[0] || 'Physical cause requires engineering field check'}
                </small>
              </div>
            )}

            {/* Key Uncertainty */}
            <div className="overview-item-card">
              <span style={{ fontSize: '9px', fontWeight: 700, textTransform: 'uppercase', color: 'var(--cv-text-muted)' }}>
                Key Uncertainty & Gaps
              </span>
              <div style={{ fontSize: '11px', color: 'var(--cv-text-secondary)' }}>
                Missing: {i.trace.missing_fields.map(human).join(', ') || 'No admitted component gaps; field cause unverified.'}
              </div>
              <small style={{ fontSize: '10px', color: 'var(--cv-text-muted)' }}>
                Conflicts: {i.trace.conflicts.map(human).join(', ') || 'None among admitted evidence.'}
              </small>
            </div>
          </div>
        )}

        {/* ================= TAB 2: EVIDENCE ================= */}
        {tab === 'evidence' && (
          <div className="tab-content">
            <div style={{ fontSize: '11px', color: 'var(--cv-text-muted)' }}>
              Report claims and AI image suggestions are not field verification. Human-reviewed labels, originals, and extraction provenance remain visible.
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {i.trace.member_evidence.map(e => {
                const source = signals.find(s => s.signal_id === e.signal_id)
                const image = source?.source_family === 'image' ? source.image_url : null
                const reviewedImage = source?.source_family === 'image' && source.provenance.annotation_method === 'human_reviewed'
                const wording = e.field_verified
                  ? `Engineer field-verified ${human(e.feature)}`
                  : reviewedImage
                  ? `Human-reviewed image label: ${human(e.feature)}`
                  : e.basis === 'visually_suggested'
                  ? `AI visual suggestion: ${human(e.feature)}`
                  : e.basis === 'reported'
                  ? `Citizen report: ${human(e.feature)}`
                  : `${human(e.basis)}: ${human(e.feature)}`

                return (
                  <article className="evidence-item" key={e.evidence_id}>
                    <div className="evidence-source-line">
                      <span>{source ? `${human(source.source_family)} observation · ${time(source.observed_at)} Cairo` : 'Linked observation'}</span>
                      {source && <span>{human(source.provenance.content_origin)}</span>}
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <strong style={{ fontSize: '11px', color: 'var(--cv-text-primary)' }}>{wording}</strong>
                      <span className={`prov-badge ${e.field_verified ? 'prov-human' : e.basis === 'visually_suggested' ? 'prov-ai' : 'prov-citizen'}`}>
                        {e.state}
                      </span>
                    </div>

                    <small style={{ color: 'var(--cv-text-muted)' }}>
                      {e.field_verified
                        ? 'Physical field check'
                        : reviewedImage
                        ? 'Human review of visible pixels; physical cause unverified.'
                        : e.basis === 'visually_suggested'
                        ? 'AI suggestion from visible pixels; physical cause unverified.'
                        : 'Citizen-reported claim; not field verified.'}
                    </small>

                    {e.span && (
                      <p className="evidence-quote" dir="auto">
                        “{e.span}”
                      </p>
                    )}

                    {image && (
                      <a href={image} target="_blank" rel="noreferrer" title="Open source image in new tab">
                        <img className="evidence-image-thumb" src={image} alt="Source infrastructure evidence" />
                      </a>
                    )}

                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 4 }}>
                      <button
                        className="btn-sm"
                        onClick={() => source && onInspectSignal(source)}
                      >
                        Inspect observation
                      </button>
                      <details><summary>Evidence ID</summary><code>{e.evidence_id}</code></details>
                    </div>
                  </article>
                )
              })}
            </div>

            {/* Environmental & Road Context */}
            <div className="overview-item-card" style={{ marginTop: 8 }}>
              <span style={{ fontSize: '9px', fontWeight: 700, textTransform: 'uppercase', color: 'var(--cv-text-muted)' }}>
                Preceding Rainfall & Context
              </span>
              <div style={{ fontSize: '11px', color: 'var(--cv-text-secondary)', marginTop: 2 }}>
                {i.trace.context.rainfall
                  ? `${i.trace.context.rainfall.hourly_mm.reduce((a, b) => a + b, 0)} mm preceding-6h rainfall (${i.trace.context.rainfall.provenance.content_origin === 'synthetic' ? 'synthetic model' : 'ERA5 reanalysis'}).`
                  : 'Rainfall unknown: no valid preceding-six-hour context.'}
              </div>
              {i.trace.context.rainfall?.source && (
                <small style={{ fontSize: '9px', color: 'var(--cv-text-muted)', marginTop: 2 }}>
                  Open-Meteo / ERA5 · Resolution {i.trace.context.rainfall.source.resolution_degrees}°. Provider model output, not a street rain gauge.
                </small>
              )}
            </div>
          </div>
        )}

        {/* ================= TAB 3: HYPOTHESES ================= */}
        {tab === 'hypotheses' && (
          <div className="tab-content">
            <div style={{ fontSize: '11px', color: 'var(--cv-text-muted)' }}>
              {i.hypothesis_abstention
                ? 'Abstaining: Current evidence does not distinguish a leading explanation.'
                : 'Support points indicate heuristic alignment, not probabilities. Physical cause requires field check.'}
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {i.hypotheses.map(h => (
                <details className="hypothesis" key={h.hypothesis_id}>
                  <summary style={{ cursor: 'pointer', padding: '6px 8px', background: 'var(--cv-surface-sidebar)', borderRadius: 5 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <strong style={{ fontSize: '12px', color: 'var(--cv-text-primary)' }}>
                        {h.hypothesis_id} · {h.title}
                      </strong>
                      <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--cv-brand-dark)' }}>
                        {h.support_points.toFixed(2)} pts
                      </span>
                    </div>
                    <div style={{ fontSize: '10px', color: 'var(--cv-brand-primary)', fontWeight: 600, marginTop: 2 }}>
                      {h.tied_or_leading}
                    </div>
                  </summary>

                  <div style={{ padding: '8px 10px' }}>
                    <Trace items={h.contributions} />
                    {h.tied_with.length > 0 && (
                      <p style={{ fontSize: '10px', color: 'var(--cv-risk-med)', marginTop: 4 }}>
                        Indistinguishable within 1 point: {h.tied_with.join(', ')}
                      </p>
                    )}
                    <p style={{ fontSize: '10px', color: 'var(--cv-text-muted)', marginTop: 4 }}>
                      Missing discriminators: {h.missing_discriminators.join('; ') || 'None in this rule set; field cause unverified.'}
                    </p>
                  </div>
                </details>
              ))}
            </div>
          </div>
        )}

        {/* ================= TAB 4: REVIEW & PROVENANCE ================= */}
        {tab === 'review' && (
          <div className="tab-content">
            <div style={{ fontSize: '11px', fontWeight: 700, textTransform: 'uppercase', color: 'var(--cv-text-muted)' }}>
              Recommended municipal action
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {i.trace.inspection_checks.map(c => (
                <div key={c.rule_id} style={{ display: 'flex', gap: 8, padding: '6px 8px', background: 'var(--cv-surface-sidebar)', borderRadius: 5 }}>
                  <span style={{ color: 'var(--cv-brand-primary)', fontWeight: 700 }}>□</span>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <span style={{ fontSize: '11px', color: 'var(--cv-text-primary)' }}>{c.text}</span>
                    <details><summary>Supporting evidence</summary><small>Rule: {c.rule_id} · Evidence: {c.evidence_ids.join(', ')}</small></details>
                  </div>
                </div>
              ))}
            </div>

            <details style={{ marginTop: 8 }}>
              <summary style={{ fontSize: '11px', fontWeight: 600, cursor: 'pointer' }}>
                Why Grouped / Why Separate?
              </summary>
              <div style={{ padding: '8px 0', fontSize: '11px', display: 'flex', flexDirection: 'column', gap: 4 }}>
                <p>Maximum member distance: {i.max_pair_distance_m.toFixed(1)} m. Observed {time(i.first_observed_at)}–{time(i.last_observed_at)} Cairo.</p>
                {i.trace.membership_reasons.map(m => (
                  <p key={m.signal_id}>
                    <b>{m.signal_id}</b>: {m.duplicate_of ? `Dependent copy of ${m.duplicate_of}` : `Capture ${m.capture_group_id}`}
                    <br /><small style={{ color: 'var(--cv-text-muted)' }}>{m.rule_ids.join(' · ')}</small>
                  </p>
                ))}
                {i.trace.excluded_evidence.length > 0 && (
                  <>
                    <h4 style={{ fontSize: '11px', marginTop: 6 }}>Excluded or separate evidence</h4>
                    {i.trace.excluded_evidence.map((e, idx) => (
                      <p key={idx}>{e.signal_id} <small style={{ color: 'var(--cv-text-muted)' }}>{e.rule_ids.join(' · ')}</small></p>
                    ))}
                  </>
                )}
              </div>
            </details>

            {/* Human Observation Review & Correction Workflow */}
            <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid var(--cv-border-light)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <span style={{ fontSize: '11px', fontWeight: 700, textTransform: 'uppercase', color: 'var(--cv-text-muted)' }}>
                  Observation Review & Correction
                </span>
                <span style={{ fontSize: '10px', color: 'var(--cv-brand-primary)', fontWeight: 600 }}>
                  Revision Lineage
                </span>
              </div>

              {i.signal_ids.length > 1 && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                  <label htmlFor="member-obs-select" style={{ fontSize: '10px', color: 'var(--cv-text-muted)', whiteSpace: 'nowrap' }}>
                    Member:
                  </label>
                  <select
                    id="member-obs-select"
                    style={{ fontSize: '11px', padding: '2px 6px', width: '100%', borderRadius: 4, border: '1px solid var(--cv-border-light)' }}
                    value={selectedSid}
                    onChange={e => { setSelectedSid(e.target.value); setEditing(false); }}
                  >
                    {i.signal_ids.map(sid => {
                      const sig = signals.find(s => s.signal_id === sid)
                      return (
                        <option key={sid} value={sid}>
                          {human(sig?.source_family || 'Observation')} observation {i.signal_ids.indexOf(sid) + 1} · {time(sig?.observed_at || null)}
                        </option>
                      )
                    })}
                  </select>
                </div>
              )}

              {jobLoading ? (
                <p style={{ fontSize: '11px', color: 'var(--cv-text-muted)', padding: 6 }}>Loading observation review state…</p>
              ) : job ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, background: 'var(--cv-surface-sidebar)', padding: 8, borderRadius: 6 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span className={`qc-pill ${job.status === 'needs_review' ? 'qc-pill-watch' : 'qc-pill-candidate'}`}>
                        {job.status === 'needs_review' ? 'Needs Review' : human(job.status)}
                      </span>
                      <span style={{ fontSize: '10px', fontWeight: 600 }}>Rev {job.revision}</span>
                      <span style={{ fontSize: '9px', color: 'var(--cv-text-muted)', textTransform: 'uppercase' }}>
                        {isImageJob(job) ? 'Image' : 'Text'}
                      </span>
                    </div>
                    {job.latest?.source && (
                      <span style={{ fontSize: '9px', color: job.latest.source === 'manual' ? 'var(--cv-brand-primary)' : 'var(--cv-text-muted)', fontWeight: 600 }}>
                        {job.latest.source === 'manual' ? '● Human Reviewed' : 'AI Extracted'}
                      </span>
                    )}
                  </div>

                  {/* Original Source Quote or Image */}
                  {job.original.text && (
                    <blockquote dir="auto" style={{ margin: 0, padding: '6px 8px', background: '#FFFFFF', borderRadius: 4, borderLeft: '3px solid var(--cv-brand-primary)', fontSize: '11px', lineHeight: 1.4 }}>
                      “{job.original.text}”
                    </blockquote>
                  )}
                  {isImageJob(job) && (job.original.image_url || job.latest?.extraction) && (
                    <div style={{ margin: '4px 0' }}>
                      {job.original.image_url && (
                        <a href={job.original.image_url} target="_blank" rel="noreferrer" style={{ display: 'block' }}>
                          <img src={job.original.image_url} alt="Original observation" style={{ width: '100%', maxHeight: 120, objectFit: 'cover', borderRadius: 4 }} />
                        </a>
                      )}
                    </div>
                  )}

                  {/* Latest Extraction State */}
                  {job.latest && (
                    <div style={{ fontSize: '10px' }}>
                      {isImageJob(job) ? (
                        <ImageResult job={job} />
                      ) : (
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '10px' }}>
                          <tbody>
                            {conditions.map(f => {
                              const ext = (job.latest as Revision | null)?.extraction
                              const state = ext ? ext[f] : 'not_mentioned'
                              return (
                                <tr key={f} style={{ borderBottom: '1px solid var(--cv-border-light)' }}>
                                  <td style={{ padding: '2px 0', color: 'var(--cv-text-muted)', textTransform: 'capitalize' }}>{human(f)}</td>
                                  <td style={{ padding: '2px 0', textAlign: 'right', fontWeight: 700 }}>
                                    {human(state).toUpperCase()}
                                  </td>
                                </tr>
                              )
                            })}
                          </tbody>
                        </table>
                      )}
                    </div>
                  )}

                  {/* Provenance and Lineage Drawer */}
                  <details style={{ fontSize: '10px' }}>
                    <summary style={{ cursor: 'pointer', color: 'var(--cv-text-muted)' }}>
                      Provenance lineage ({job.revisions.length} revision{job.revisions.length === 1 ? '' : 's'})
                    </summary>
                    <div style={{ padding: '4px 0' }}>
                      <p style={{ margin: '2px 0' }}>Author / Operator: {reviewerLabel(job.original.operator)}</p>
                      <p style={{ margin: '2px 0' }}>Origin: {job.original.content_origin} content · {job.original.placement_origin || 'original'} placement</p>
                      {job.revisions.map((rev, rIdx) => (
                        <div key={rIdx} style={{ margin: '3px 0', padding: '2px 4px', background: '#FFFFFF', borderRadius: 3 }}>
                          <strong>Rev {rev.revision}</strong> · {rev.source === 'manual' ? 'Human review' : rev.source} · {human(rev.review_state)}
                          {rev.model && <small style={{ display: 'block', color: 'var(--cv-text-muted)' }}>Model: {rev.model}</small>}
                        </div>
                      ))}
                    </div>
                  </details>

                  {/* Correction Form Toggle & ReviewForm */}
                  {!editing ? (
                    <button
                      type="button"
                      className="btn-sm primary"
                      style={{ alignSelf: 'flex-start' }}
                      onClick={() => setEditing(true)}
                    >
                      {isImageJob(job) ? 'Correct image labels' : 'Correct extraction'}
                    </button>
                  ) : (
                    <div style={{ borderTop: '1px solid var(--cv-border-light)', paddingTop: 6 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                        <span style={{ fontSize: '11px', fontWeight: 700 }}>Correct Extraction</span>
                        <button type="button" className="btn-sm" onClick={() => setEditing(false)}>Cancel</button>
                      </div>
                      {isImageJob(job) ? (
                        <ImageReviewForm
                          key={job.signal_id + ':' + job.revision}
                          job={job}
                          saved={updated => {
                            setJob(updated)
                            setEditing(false)
                            onReviewSaved?.()
                          }}
                        />
                      ) : (
                        <ReviewForm
                          key={job.signal_id + ':' + job.revision}
                          job={job}
                          saved={updated => {
                            setJob(updated)
                            setEditing(false)
                            onReviewSaved?.()
                          }}
                        />
                      )}
                    </div>
                  )}
                </div>
              ) : (
                /* Replay or static record where processing API returns 404 */
                <div className="overview-item-card" style={{ padding: 8 }}>
                  <details><summary>Observation reference</summary><code>{selectedSid}</code></details>
                  <p style={{ fontSize: '10px', color: 'var(--cv-text-muted)', margin: '4px 0 0' }}>
                    Bundled demo observation. To record a Human Review or correction, select an operator-submitted observation.
                  </p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </aside>
  )
}

export function OperationsWorkbench() {
  const [data, setData] = useState<Replay>(empty)
  const [selected, setSelected] = useState<string | null>(null)
  const [comparison, setComparison] = useState<Comparison | null>(null)
  const [hideImage, setHideImage] = useState(false)
  const [copies, setCopies] = useState(false)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [scenario, setScenario] = useState('signature')
  const [live, setLive] = useState(false)
  const [ribbonExpanded, setRibbonExpanded] = useState(false)
  const [inspectedSignal, setInspectedSignal] = useState<Signal | null>(null)

  const requestGeneration = useRef(0)
  const loadData = useCallback(() => {
    const generation = ++requestGeneration.current
    setLoading(true)
    setError('')
    api<Replay>(live ? 'live/incidents' : 'incidents')
      .then(result => {
        if (generation === requestGeneration.current) {
          setData(result)
          setLoading(false)
        }
      })
      .catch(e => {
        if (generation === requestGeneration.current) {
          setError(String(e))
          setLoading(false)
        }
      })
  }, [live])

  useEffect(() => {
    loadData()
    setComparison(null)
    setSelected(null)
    return () => { requestGeneration.current++ }
  }, [live, loadData])

  const incidents = comparison?.incidents ?? data.incidents
  const signals = comparison?.signals ?? data.signals
  const chosen = incidents.find(i => i.incident_id === selected) ??
    incidents.find(i => i.status === 'candidate') ??
    incidents[0]

  async function handleReplay(action: 'start' | 'advance' | 'reset') {
    const generation = ++requestGeneration.current
    setBusy(true)
    setError('')
    try {
      const result = await api<Replay>('demo/replay', { action, scenario })
      if (generation !== requestGeneration.current) return
      setData(result)
      setComparison(null)
      setHideImage(false)
      setCopies(false)
      if (action === 'reset') setSelected(null)
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  async function handleCompare(image: boolean, duplicates: boolean) {
    const generation = requestGeneration.current
    const prevImage = hideImage
    const prevCopies = copies
    setBusy(true)
    setError('')
    setHideImage(image)
    setCopies(duplicates)
    try {
      const result = await api<Comparison>('demo/compare', {
        disable_families: image ? ['image'] : [],
        source_signal_id: chosen?.signal_ids.find(sid => signals.some(s => s.signal_id === sid && s.source_family === 'text' && !s.duplicate_of)),
        add_duplicates: duplicates ? 10 : 0
      })
      if (generation !== requestGeneration.current) return
      setComparison(image || duplicates ? result : null)
    } catch (e) {
      setError(String(e))
      setHideImage(prevImage)
      setCopies(prevCopies)
    } finally {
      setBusy(false)
    }
  }

  const candidateCount = incidents.filter(i => i.status === 'candidate').length
  const watchCount = incidents.filter(i => i.status === 'watch').length
  const totalCaptures = incidents.reduce((sum, i) => sum + i.independent_capture_count, 0)

  return (
    <div className="ops-viewport">
      {/* Top Bar (Height: 48px) */}
      <header className="ops-header">
        <div className="ops-header-left">
          <button className="ops-brand" onClick={() => navigate('/')}>
            <span style={{ fontSize: 18 }}>⋈</span>
            <span>Converge</span>
          </button>
          <span className="ops-sector-pill">Nasr City Study Prototype · IMPACTX 2026</span>
          <span className={`mode-pill ${live ? 'mode-live' : 'mode-sandbox'}`}>
            {live ? '● Live Municipal Mode' : '⚗ Demo Replay Mode'}
          </span>
        </div>

        <div className="ops-header-right">
          <div className="ops-clock-widget">
            <span>{time(data.clock)}</span>
            <small style={{ color: 'var(--cv-text-muted)', fontSize: '10px' }}>
              Cairo · {live ? 'live state' : 'replay clock'}
            </small>
          </div>

          <button
            className="btn-sm"
            onClick={() => { requestGeneration.current++; setLive(!live) }}
            title="Toggle between Live Municipal ingestion and Demo Replay mode"
          >
            {live ? 'Switch to Demo Replay' : 'Switch to Live Municipal'}
          </button>

          <button
            className="btn-sm primary"
            onClick={() => navigate('/report')}
          >
            + Submit Observation
          </button>
        </div>
      </header>

      {/* Comparison Sandbox Alert Banner */}
      {comparison && (
        <div className="comparison" role="status" style={{ padding: '6px 16px', fontSize: '11px' }}>
          ⚗ Active Comparison Sandbox · {hideImage ? 'image evidence family removed (ablation)' : 'all families active'} · {comparison.added_duplicates} duplicate copies injected. Baseline intact.
        </div>
      )}

      {error && (
        <div className="error" role="alert" style={{ padding: '6px 16px', fontSize: '11px' }}>
          Could not refresh this view. Previously loaded data remains unchanged. {error}
        </div>
      )}

      {loading && data.incidents.length > 0 && (
        <div className="refresh-status" role="status">
          Refreshing {live ? 'municipal records' : 'bundled replay'}… The current values remain visible until the refresh completes.
        </div>
      )}

      {/* 3-Column Split Workspace (Calibrated for 1280x720 Zero Scroll) */}
      <main className={`ops-workspace ${ribbonExpanded ? 'ribbon-expanded' : ''}`}>
        {/* Column 1: Inspection Queue */}
        <aside className="ops-col-queue" aria-label="Inspection Queue">
          <div className="queue-header-area">
            <div className="queue-title">
              <span>Inspection Queue</span>
              <span className="queue-count-badge">{candidateCount} Candidate{candidateCount === 1 ? '' : 's'}</span>
            </div>
          </div>

          <div className="queue-list">
            {incidents.filter(i => i.status === 'candidate').map(i => (
              <button
                key={i.incident_id}
                data-incident-id={i.incident_id}
                className={`queue-card ${chosen?.incident_id === i.incident_id ? 'selected' : ''}`}
                onClick={() => setSelected(i.incident_id)}
              >
                <div className="qc-top-row">
                  <span className="qc-road-name">{roadLabel(i.road_name).split(' · ')[0]}</span>
                  <div className="qc-risk-metric">
                    <span className="qc-risk-label">Risk</span>
                    <span>{i.risk.display} <small>/100</small></span>
                  </div>
                </div>
                <div className="qc-tags-row">
                  <span className="qc-pill qc-pill-candidate">Candidate</span>
                  <span style={{ fontSize: '10px', color: 'var(--cv-text-muted)' }}>{i.tag}</span>
                </div>
                <div className="qc-corroboration">
                  <strong>{i.independent_capture_count} capture{i.independent_capture_count === 1 ? '' : 's'}</strong>
                  <span>· {i.signal_ids.length} records</span>
                  <span>· {i.evidence_strength}</span>
                </div>
              </button>
            ))}

            {watchCount > 0 && (
              <>
                <div style={{ fontSize: '10px', fontWeight: 700, textTransform: 'uppercase', color: 'var(--cv-text-muted)', margin: '8px 0 2px' }}>
                  Watch Items ({watchCount})
                </div>
                {incidents.filter(i => i.status === 'watch').map(i => (
                  <button
                    key={i.incident_id}
                    data-incident-id={i.incident_id}
                    className={`queue-card ${chosen?.incident_id === i.incident_id ? 'selected' : ''}`}
                    onClick={() => setSelected(i.incident_id)}
                  >
                    <div className="qc-top-row">
                      <span className="qc-road-name">{roadLabel(i.road_name).split(' · ')[0]}</span>
                      <div className="qc-risk-metric" style={{ color: 'var(--cv-text-secondary)' }}>
                        <span className="qc-risk-label">Risk</span>
                        <span>{i.risk.display} <small>/100</small></span>
                      </div>
                    </div>
                    <div className="qc-tags-row">
                      <span className="qc-pill qc-pill-watch">Watch</span>
                      <span style={{ fontSize: '10px', color: 'var(--cv-text-muted)' }}>{i.tag}</span>
                    </div>
                    <div className="qc-corroboration">
                      <span>{i.independent_capture_count} capture{i.independent_capture_count === 1 ? '' : 's'} · {i.evidence_strength}</span>
                    </div>
                  </button>
                ))}
              </>
            )}

            {incidents.length === 0 && (
              <p className="queue-empty-state" aria-live="polite">
                {loading
                  ? `Loading ${live ? 'municipal records' : 'bundled replay'}…`
                  : live
                  ? 'No admitted municipal observations yet. Submit an observation to begin.'
                  : 'This replay has no incidents at the current step. Advance it to add observations.'}
              </p>
            )}

            {data.excluded.length > 0 && (
              <details style={{ marginTop: 8, fontSize: '10px' }}>
                <summary style={{ cursor: 'pointer', color: 'var(--cv-text-muted)' }}>
                  {data.excluded.length} records excluded from active grouping
                </summary>
                <div style={{ padding: '6px 0' }}>
                  {data.excluded.map(e => (
                    <p key={e.signal_id} style={{ margin: '3px 0' }}>
                      {e.signal_id}: <small style={{ color: 'var(--cv-text-muted)' }}>{e.rule_ids.join(', ')}</small>
                    </p>
                  ))}
                </div>
              </details>
            )}
          </div>

          <div style={{ padding: '8px 12px', borderTop: '1px solid var(--cv-border-light)', fontSize: '10px', color: 'var(--cv-text-muted)' }}>
            Inspection support. A human engineer verifies physical cause.
          </div>
        </aside>

        {/* Column 2: Cartographic Hero Map */}
        <MapPanel
          data={data}
          incidents={incidents}
          signals={signals}
          selected={chosen?.incident_id ?? null}
          onSelect={setSelected}
        />

        {/* Column 3: Tabbed Incident Inspector */}
        {chosen ? (
          <TabbedInspector
            incident={chosen}
            signals={signals}
            onInspectSignal={setInspectedSignal}
            onReviewSaved={loadData}
          />
        ) : (
          <aside className="ops-col-inspector" style={{ padding: 20, textAlign: 'center', justifyContent: 'center' }}>
            <h3 style={{ fontSize: '14px', marginBottom: 6 }}>Cross-Signal Incident Intelligence</h3>
            <p style={{ fontSize: '11px', color: 'var(--cv-text-secondary)' }}>
              Select an incident from the queue or click on the map to inspect evidence convergence.
            </p>
          </aside>
        )}
      </main>

      {/* Signature Collapsible Convergence Ribbon (Footer Drawer) */}
      <footer className="ops-bottom-tray">
        <div
          className="ribbon-handle-bar"
          onClick={() => setRibbonExpanded(!ribbonExpanded)}
          role="button"
          tabIndex={0}
          aria-expanded={ribbonExpanded}
          onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') setRibbonExpanded(!ribbonExpanded) }}
        >
          <div className="ribbon-handle-title">
            <span style={{ color: 'var(--cv-brand-primary)' }}>{ribbonExpanded ? '▼' : '▲'}</span>
            <span>Multi-Signal Convergence Ribbon</span>
            <small style={{ color: 'var(--cv-text-muted)', fontWeight: 400 }}>
              · {signals.length} records across {totalCaptures} independent captures · {live ? 'Current observations' : `Step ${data.step}/${data.total_steps}`}
            </small>
          </div>
          <button
            type="button"
            className="ribbon-toggle-btn"
            onClick={(e) => { e.stopPropagation(); setRibbonExpanded(!ribbonExpanded) }}
          >
            {ribbonExpanded ? 'Collapse Ribbon ▼' : 'Expand Timeline ▲'}
          </button>
        </div>

        {ribbonExpanded && (
          <div className="ribbon-expanded-content">
            {/* Timeline Stream */}
            <div className="tray-timeline-area">
              {[...signals]
                .sort((a, b) => a.observed_at.localeCompare(b.observed_at) || a.signal_id.localeCompare(b.signal_id))
                .map(s => {
                  const isMember = chosen?.signal_ids.includes(s.signal_id)
                  return (
                    <div
                      key={s.signal_id}
                      className={`timeline-node ${isMember ? 'highlight' : ''}`}
                      onClick={() => {
                        const targetIncident = incidents.find(inc => inc.signal_ids.includes(s.signal_id))
                        if (targetIncident) setSelected(targetIncident.incident_id)
                        setInspectedSignal(s)
                      }}
                      style={{ cursor: 'pointer' }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <strong>{time(s.observed_at)}</strong>
                        <span style={{ fontSize: '9px', textTransform: 'uppercase', color: 'var(--cv-text-muted)' }}>
                          {s.source_family}
                        </span>
                      </div>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px' }}>{human(s.source_family)} observation</span>
                      <small style={{ color: isMember ? 'var(--cv-brand-primary)' : 'var(--cv-text-muted)' }}>
                        {s.duplicate_of ? 'Duplicate report' : 'Source capture'}
                      </small>
                    </div>
                  )
                })}
              {signals.length === 0 && (
                <span style={{ fontSize: '11px', color: 'var(--cv-text-muted)', margin: 'auto' }}>
                  No observations loaded in timeline.
                </span>
              )}
            </div>

            {/* Quarantined Replay Sandbox Bar (Only in Demo Replay Mode) */}
            {!live && (
              <div className="tray-sandbox-bar">
                <div className="sandbox-tag">
                  <span>DEMO</span>
                  <strong>Demo Replay Controls:</strong>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    Scenario:
                    <select
                      value={scenario}
                      disabled={busy}
                      onChange={e => setScenario(e.target.value)}
                      style={{ fontSize: '11px', padding: '2px 4px' }}
                    >
                      {[
                        'signature', 'signature_image', 'context_signature', 'context_archive',
                        'missing_road_damage', 'conflicting_water', 'spatial_119m', 'spatial_121m',
                        'time_5h59', 'time_6h', 'time_over_6h', 'chain_guard', 'road_incompatible'
                      ].map(s => <option value={s} key={s}>{scenarioLabel(s)}</option>)}
                    </select>
                  </label>

                  <button className="btn-sm" disabled={busy || data.step > 0} onClick={() => handleReplay('start')}>
                    Start
                  </button>
                  <button className="btn-sm primary" disabled={busy || data.step === 0 || data.step >= data.total_steps} onClick={() => handleReplay('advance')}>
                    Advance
                  </button>
                  <button className="btn-sm" disabled={busy} onClick={() => handleReplay('reset')}>
                    Reset
                  </button>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={hideImage}
                      disabled={busy || !data.step}
                      onChange={e => handleCompare(e.target.checked, copies)}
                    />
                    Hide image evidence
                  </label>

                  <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={copies}
                      disabled={busy || !data.step}
                      onChange={e => handleCompare(hideImage, e.target.checked)}
                    />
                    Add 10 duplicate reports
                  </label>
                </div>
              </div>
            )}
          </div>
        )}
      </footer>

      {/* Raw Signal Inspector Drawer/Modal */}
      {inspectedSignal && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(15, 23, 42, 0.45)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: 20
          }}
          onClick={() => setInspectedSignal(null)}
        >
          <div
            style={{
              maxWidth: 480,
              width: '100%',
              background: '#FFFFFF',
              borderRadius: 8,
              padding: 20,
              boxShadow: '0 8px 30px rgba(0,0,0,0.12)',
              display: 'flex',
              flexDirection: 'column',
              gap: 12
            }}
            onClick={e => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <strong style={{ fontSize: '14px' }}>Observation details</strong>
              <button className="btn-sm" onClick={() => setInspectedSignal(null)}>Close ✕</button>
            </div>

            {inspectedSignal.source_family === 'image' ? (
              inspectedSignal.image_url ? (
                <a href={inspectedSignal.image_url} target="_blank" rel="noreferrer">
                  <img
                    src={inspectedSignal.image_url}
                    alt="Source observation"
                    style={{ width: '100%', height: 180, objectFit: 'cover', borderRadius: 6 }}
                  />
                </a>
              ) : (
                <p style={{ color: 'var(--cv-text-muted)' }}>Structured legacy image record without local preview.</p>
              )
            ) : (
              <div style={{ background: 'var(--cv-surface-sidebar)', padding: 12, borderRadius: 6 }}>
                <span style={{ fontSize: '10px', color: 'var(--cv-text-muted)', display: 'block', marginBottom: 4 }}>Report text</span>
                <p dir="auto" style={{ fontSize: '13px', lineHeight: 1.5 }}>{inspectedSignal.text}</p>
              </div>
            )}

            <div style={{ fontSize: '11px', display: 'flex', flexDirection: 'column', gap: 4, background: 'var(--cv-surface-bg)', padding: 10, borderRadius: 6 }}>
              <div><strong>Observed:</strong> {inspectedSignal.observed_at} ({time(inspectedSignal.observed_at)} Cairo)</div>
              <div><strong>Received:</strong> {inspectedSignal.received_at} ({time(inspectedSignal.received_at)} Cairo)</div>
              <details><summary>Technical identifiers</summary><div><strong>Observation ID:</strong> {inspectedSignal.signal_id}</div><div><strong>Capture Group:</strong> {inspectedSignal.capture_group_id}</div>
              {inspectedSignal.duplicate_of && <div><strong>Duplicate Of:</strong> {inspectedSignal.duplicate_of}</div>}
              <div><strong>Recorded author / reviewer:</strong> {inspectedSignal.provenance.reviewer}</div>{inspectedSignal.provenance.source_ref && <div><strong>Source Ref:</strong> {inspectedSignal.provenance.source_ref}</div>}</details><div><strong>Provenance:</strong> {human(inspectedSignal.provenance.content_origin)} content · {human(inspectedSignal.provenance.annotation_method)}</div>
              <div><strong>Placement / time:</strong> {human(inspectedSignal.provenance.placement_origin)} placement · {human(inspectedSignal.provenance.time_origin)} time</div><div><strong>Author / Reviewer:</strong> {reviewerLabel(inspectedSignal.provenance.reviewer)}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
