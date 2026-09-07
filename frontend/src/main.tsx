import React, { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import * as maplibregl from 'maplibre-gl'
import type { GeoJSONSource } from 'maplibre-gl'
import type { Feature } from 'geojson'
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import 'maplibre-gl/dist/maplibre-gl.css'
import './style.css'
import type { Comparison, Contribution, Incident, Replay, Signal } from './types'
import { ObservationPanel } from './ObservationPanel'

maplibregl.setWorkerUrl(mapWorkerUrl)

const empty: Replay = {dataset_id: null, incidents: [], signals: [], roads: [], step: 0, total_steps: 0, clock: null, mode: 'manual_structured', excluded: []}
const human = (s: string) => s.replaceAll('_', ' ')
const time = (s: string | null) => s ? new Intl.DateTimeFormat('en-GB', {timeZone: 'Africa/Cairo', hour: '2-digit', minute: '2-digit'}).format(new Date(s)) : '—'
async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch('/api/v1/' + path, body ? {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)} : undefined)
  if (!response.ok) { const detail = await response.text(); throw new Error(`Request failed (${response.status}): ${detail}`) }
  return response.json()
}

function Trace({items}: {items: Contribution[]}) {
  return <ul className="trace">{items.map(c => <li key={c.rule_id}><code>{c.rule_id}</code><span>{c.weight} × {c.strength.toFixed(3)} = {c.points.toFixed(2)} points</span><small>{c.evidence_ids.join(', ') || 'Unknown component: lower bound 0, full weighted range retained.'}</small></li>)}</ul>
}

function MapPanel({data, incidents, signals, selected, onSelect}: {data: Replay; incidents: Incident[]; signals: Signal[]; selected: string | null; onSelect: (id: string) => void}) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const markers = useRef<maplibregl.Marker[]>([])
  const boundsKey = useRef('')
  const [loaded, setLoaded] = useState(false)
  const [mapError, setMapError] = useState('')
  const [rendered, setRendered] = useState(false)
  const [mapSizeVersion, setMapSizeVersion] = useState(0)
  const selectRef = useRef(onSelect)
  selectRef.current = onSelect
  useEffect(() => {
    if (!container.current) return
    try {
      const m = new maplibregl.Map({container: container.current, center: [31.336, 30.054], zoom: 15.3,
        attributionControl: false, style: {version: 8, sources: {}, layers: [{id: 'background', type: 'background', paint: {'background-color': '#eaf0ec'}}]}})
      map.current = m
      m.addControl(new maplibregl.NavigationControl({showCompass: false}), 'top-right')
      m.on('load', () => {
        for (const name of ['roads', 'areas', 'observations', 'incidents']) m.addSource(name, {type: 'geojson', data: {type: 'FeatureCollection', features: []}})
        m.addLayer({id: 'roads', type: 'line', source: 'roads', paint: {'line-color': '#c0ccc5', 'line-width': 12}})
        m.addLayer({id: 'road-center', type: 'line', source: 'roads', paint: {'line-color': '#fcfdfb', 'line-width': 7}})
        m.addLayer({id: 'areas', type: 'fill', source: 'areas', paint: {'fill-color': '#257767', 'fill-opacity': 0.10}})
        m.addLayer({id: 'area-line', type: 'line', source: 'areas', paint: {'line-color': '#257767', 'line-width': 1, 'line-dasharray': [3, 3]}})
        m.addLayer({id: 'observations', type: 'circle', source: 'observations', paint: {'circle-radius': 5,
          'circle-color': ['match', ['get', 'family'], 'image', '#a06d27', '#438f98'], 'circle-stroke-width': 2, 'circle-stroke-color': '#fff'}})
        m.addLayer({id: 'incidents', type: 'circle', source: 'incidents', paint: {
          'circle-radius': ['case', ['get', 'selected'], 17, 12], 'circle-opacity': 0.85,
          'circle-color': ['match', ['get', 'status'], 'candidate', '#b85c35', '#5c7772'],
          'circle-stroke-width': ['case', ['get', 'selected'], 4, 2], 'circle-stroke-color': '#fff'}})
        m.on('click', 'incidents', e => {const id = e.features?.[0]?.properties?.id; if (id) selectRef.current(id)})
        m.on('mouseenter', 'incidents', () => {m.getCanvas().style.cursor = 'pointer'})
        m.on('mouseleave', 'incidents', () => {m.getCanvas().style.cursor = ''})
        setLoaded(true)
      })
      m.on('error', e => setMapError(e.error.message))
      m.on('idle', () => {if (m.getLayer('roads')) setRendered(m.queryRenderedFeatures({layers: ['roads']}).length > 0)})
      m.on('resize', () => {boundsKey.current = ''; setMapSizeVersion(v => v + 1)})
      const observer = new ResizeObserver(() => m.resize()); observer.observe(container.current)
      return () => {observer.disconnect(); m.remove(); map.current = null}
    } catch (e) {setMapError(String(e))}
  }, [])
  useEffect(() => {
    const m = map.current
    if (!m || !loaded) return
    const set = (name: string, features: Feature[]) => (m.getSource(name) as GeoJSONSource).setData({type: 'FeatureCollection', features})
    set('roads', data.geography?.features ?? data.roads.map(r => ({type: 'Feature', properties: {}, geometry: {type: 'LineString', coordinates: r.coordinates}})))
    set('observations', signals.map(s => ({type: 'Feature', properties: {family: s.source_family}, geometry: {type: 'Point', coordinates: [s.lon, s.lat]}})))
    set('incidents', incidents.map(i => ({type: 'Feature', properties: {id: i.incident_id, selected: i.incident_id === selected, status: i.status}, geometry: {type: 'Point', coordinates: [i.lon, i.lat]}})))
    const chosen = incidents.find(i => i.incident_id === selected)
    set('areas', chosen ? [{type: 'Feature', properties: {}, geometry: {type: 'Polygon', coordinates: [Array.from({length: 49}, (_, n) => {
      const angle = n * 2 * Math.PI / 48
      return [chosen.lon + Math.cos(angle) * 120 / (111195 * Math.cos(chosen.lat * Math.PI / 180)), chosen.lat + Math.sin(angle) * 120 / 111195]
    })]}}] : [])
    markers.current.forEach(marker => marker.remove())
    markers.current = incidents.map(i => {
      const label = document.createElement('button')
      label.className = 'map-label'
      label.textContent = i.road_name.split(' · ')[0]
      label.setAttribute('aria-label', `Select map ${label.textContent}`)
      label.onclick = () => selectRef.current(i.incident_id)
      return new maplibregl.Marker({element: label, offset: [0, -31]}).setLngLat([i.lon, i.lat]).addTo(m)
    })
    const locations = [...new Set(signals.map(s => `${s.lon},${s.lat}`))].sort()
    const key = locations.join(';')
    if (key && key !== boundsKey.current) {
      boundsKey.current = key
      const bounds = new maplibregl.LngLatBounds()
      signals.forEach(s => bounds.extend([s.lon, s.lat]))
      m.fitBounds(bounds, {padding: {top: 150, bottom: 105, left: 60, right: 60}, maxZoom: 16, duration: 0})
    }
  }, [data.roads, data.geography, incidents, signals, selected, loaded, mapSizeVersion])
  return <section className="map-panel" aria-label="Study area map"><div ref={container} className="map"/>
    <div className="map-caption"><b>Nasr City study extent</b><span>{data.context_notice ? 'Real OSM geography · synthetic incident placement' : data.mode.startsWith('operator_') ? 'Operator coordinates · reviewed road context' : 'Schematic demo segments · simulated geography'}</span>{data.roads.some(r => r.source?.provider === 'OpenStreetMap') && <small><a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap contributors · ODbL</a></small>}<small>{data.mode.startsWith('operator_') ? 'Local observation pins' : rendered ? 'Local vector map ready' : data.step ? 'Loading local map…' : 'Start replay to load study segments'}</small></div>
    <div className="map-legend"><span>● Candidate</span><span>● Watch item</span><small>Dashed ring: 120 m reference, not an incident footprint.</small></div>
    {mapError && <p className="map-error" role="alert">Map unavailable: {mapError}. Select locations in the queue.</p>}
  </section>
}

function Detail({incident: i, signals}: {incident: Incident; signals: Signal[]}) {
  const [original, setOriginal] = useState<Signal | null>(null)
  useEffect(() => setOriginal(null), [i.incident_id])
  return <aside className="detail" aria-label="Incident details">
    <div className="eyebrow">{i.status === 'candidate' ? 'Candidate incident' : 'Watch item'} · revision {i.revision}</div>
    <h2>Why inspect here?</h2><h3>{i.road_name}</h3>
    <p>{i.independent_capture_count} independent capture{i.independent_capture_count === 1 ? '' : 's'} across {i.signal_ids.length} records. {i.tag}.</p>
    <small className="rule">{i.trace.formation_rule}</small>
    <div className="risk"><span>Risk index — inspection triage</span><strong>{i.risk.display}<small>/100</small></strong><b>{i.risk.risk_band}{i.risk.provisional && i.risk.risk_band !== 'provisional' ? ' · provisional range' : ''}</b><small>Impact heuristic · physical cause unverified</small></div>
    <div className="strength"><span>Evidence strength</span><b>{i.evidence_strength}</b><small>{i.trace.evidence_strength_rule}</small></div>
    <details><summary>Risk components & calculation</summary>
      <table><tbody>{Object.entries(i.risk.components).map(([key, value]) => <tr key={key}><th>{human(key)}</th><td>{value === null ? 'Unknown' : value}</td></tr>)}</tbody></table>
      <p>{Math.round(i.risk.known_component_coverage * 100)}% of component weight is known. This is coverage, not confidence.</p><Trace items={i.risk.contributions}/><small>{i.risk.rule_version}</small>
    </details>
    <section><h3>Working interpretations</h3><p className="muted">{i.hypothesis_abstention ? 'Abstaining: current evidence does not distinguish a leading explanation.' : 'Support points, not probabilities. Physical cause needs field verification.'}</p>
      {i.hypotheses.map(h => <details className="hypothesis" key={h.hypothesis_id}><summary><span><b>{h.hypothesis_id} · {h.support_points.toFixed(2)} points</b><em>{h.tied_or_leading}</em><span>{h.title}</span></span></summary><Trace items={h.contributions}/><p>{h.tied_with.length > 0 && `Not distinguishable within 1 point: ${h.tied_with.join(', ')}.`}</p><p>Missing discriminators: {h.missing_discriminators.join('; ') || 'None in this rule set; field cause remains unverified.'}</p></details>)}
    </section>
    <details><summary>Why grouped / why separate?</summary><p>Maximum member distance: {i.max_pair_distance_m.toFixed(1)} m. Observed {time(i.first_observed_at)}–{time(i.last_observed_at)} Cairo.</p>
      {i.trace.membership_reasons.map(m => <p key={m.signal_id}><b>{m.signal_id}</b><br/>{m.duplicate_of ? `Dependent copy of ${m.duplicate_of}` : `Capture ${m.capture_group_id}`}<small className="rule">{m.rule_ids.join(' · ')}</small></p>)}
      <h4>Excluded or separate evidence</h4>{i.trace.excluded_evidence.map((e, n) => <p key={n}>{e.signal_id}<small className="rule">{e.rule_ids.join(' · ')}</small></p>)}
    </details>
    <section><h3>Contributing evidence</h3><p className="muted">Report claims and AI image suggestions are not field verification. Human-reviewed labels, originals and extraction provenance remain visible.</p>
      {i.trace.member_evidence.map(e => {const source = signals.find(s => s.signal_id === e.signal_id); const image = source?.source_family === 'image' ? source.image_url : null; const reviewedImage = source?.source_family === 'image' && source.provenance.annotation_method === 'human_reviewed'; const wording = e.field_verified ? `Engineer field-verified ${human(e.feature)}` : reviewedImage ? `Engineer verified image label: ${human(e.feature)}` : e.basis === 'visually_suggested' ? `Image suggests ${human(e.feature)}` : e.basis === 'reported' ? `Report states ${human(e.feature)}` : `${human(e.basis)} evidence`; return <article className="evidence" key={e.evidence_id}><b>{wording} · {e.state}</b><small>{e.field_verified ? 'Physical field verification' : reviewedImage ? 'Human review of visible pixels; physical cause and severity remain unverified.' : e.basis === 'visually_suggested' ? 'AI suggestion from visible pixels; physical cause and severity remain unverified.' : 'Citizen-reported claim; not field verified.'}</small>{image && <a className="evidence-image" href={image} target="_blank" rel="noreferrer"><img src={image} alt="Source infrastructure image"/><span>Open source image</span></a>}<p>{e.span}</p><button className="link" onClick={() => setOriginal(source ?? null)}>Open record {e.signal_id}</button><code>{e.evidence_id}</code></article>})}
      {original && <div className="original"><button onClick={() => setOriginal(null)}>Close record</button><h4>{original.signal_id}</h4>{original.source_family === 'image' ? original.image_url ? <a className="evidence-image" href={original.image_url} target="_blank" rel="noreferrer"><img src={original.image_url} alt="Saved source infrastructure image"/><span>Open source image</span></a> : <p>No source-image file is attached to this legacy structured record.</p> : <p dir="auto">{original.text}</p>}<p>Observed {time(original.observed_at)} · available {time(original.available_at)} Cairo</p><small>{original.provenance.content_origin} content · {original.provenance.placement_origin} placement · {original.provenance.time_origin} time</small><small>{original.provenance.reviewer}</small></div>}
      <div className="context"><b>Rainfall / road context</b><p>{i.trace.context.rainfall ? `${i.trace.context.rainfall.hourly_mm.reduce((a, b) => a + b, 0)} mm ${i.trace.context.rainfall.provenance.content_origin === 'synthetic' ? 'synthetic' : 'modeled Open-Meteo ERA5'} preceding-six-hour rainfall. ${i.trace.context.rainfall.context_id}` : 'Rainfall unknown: no complete valid preceding-six-hour context.'}</p>{i.trace.context.rainfall?.source && <p><a href="https://open-meteo.com/en/docs/historical-weather-api" target="_blank" rel="noreferrer">Open-Meteo / ERA5 · CC BY 4.0</a><br/>Grid {i.trace.context.rainfall.source.grid_center?.join(', ')} · {i.trace.context.rainfall.source.resolution_degrees}°; valid to {i.trace.context.rainfall.end_at}.<br/>Acquired {i.trace.context.rainfall.source.acquired_at}. {i.trace.context.rainfall.source.application === 'retrospective_demo' ? 'Retrospective context in a synthetic replay; not available as-issued. No real incident is claimed.' : 'Provider model output, not a street rain gauge.'}</p>}<details><summary>Road source and context provenance</summary>{i.trace.context.roads.map(r => <p key={r.road_context_id}>{r.name} · {r.provenance.content_origin}<br/>{r.source ? <a href={r.provenance.source_ref} target="_blank" rel="noreferrer">OpenStreetMap way · ODbL</a> : r.provenance.source_ref}<br/>{r.source?.acquired_at}<br/>{r.provenance.reviewer}</p>)}{i.trace.context.rainfall?.source && <small>Raw response SHA-256: {i.trace.context.rainfall.source.raw_sha256}</small>}</details><small>Context adds no independent captures. Road exposure uses a reviewed class when available.</small></div>
    </section>
    <section className="uncertainty"><h3>Missing / conflicting evidence</h3><p>Missing: {i.trace.missing_fields.map(human).join(', ') || 'No component gaps; physical cause remains unverified.'}</p><p>Conflicts: {i.trace.conflicts.map(human).join(', ') || 'None among admitted current evidence.'}</p>
      {Object.entries(i.features).map(([key, f]) => <details key={key}><summary>{human(key)} · {f.state}</summary><small>{f.rule_id}</small><small>{f.evidence_ids.join(', ') || 'No admitted evidence'}</small></details>)}
    </section>
    <section><h3>Recommended inspection checks</h3>{i.trace.inspection_checks.map(c => <div className="check" key={c.rule_id}><span>□</span><div>{c.text}<small>{c.rule_id} · {c.evidence_ids.join(', ')}</small></div></div>)}</section>
  </aside>
}

function App() {
  const [data, setData] = useState<Replay>(empty)
  const [selected, setSelected] = useState<string | null>(null)
  const [comparison, setComparison] = useState<Comparison | null>(null)
  const [hideImage, setHideImage] = useState(false)
  const [copies, setCopies] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [scenario, setScenario] = useState('signature')
  const [live, setLive] = useState(false)
  const [showObservations, setShowObservations] = useState(false)
  useEffect(() => {api<Replay>(live ? 'live/incidents' : 'incidents').then(setData).catch(e => setError(String(e))); setComparison(null); setSelected(null)}, [live])
  const refreshLive = React.useCallback(() => {setLive(true); api<Replay>('live/incidents').then(setData).catch(e => setError(String(e)))}, [])
  const incidents = comparison?.incidents ?? data.incidents
  const signals = comparison?.signals ?? data.signals
  const chosen = incidents.find(i => i.incident_id === selected) ?? incidents.find(i => i.status === 'candidate') ?? incidents[0]
  async function replay(action: 'start' | 'advance' | 'reset') {
    setBusy(true); setError('')
    try {setData(await api<Replay>('demo/replay', {action, scenario})); setComparison(null); setHideImage(false); setCopies(false); if (action === 'reset') setSelected(null)}
    catch (e) {setError(String(e))} finally {setBusy(false)}
  }
  async function compare(image: boolean, duplicates: boolean) {
    const previousImage = hideImage, previousCopies = copies
    setBusy(true); setError(''); setHideImage(image); setCopies(duplicates)
    try {const result = await api<Comparison>('demo/compare', {disable_families: image ? ['image'] : [], add_duplicates: duplicates ? 10 : 0}); setComparison(image || duplicates ? result : null); setHideImage(image); setCopies(duplicates)}
    catch (e) {setError(String(e)); setHideImage(previousImage); setCopies(previousCopies)} finally {setBusy(false)}
  }
  const queue = (status: 'watch' | 'candidate') => incidents.filter(i => i.status === status).map(i => <button key={i.incident_id} className={'queue-card ' + (chosen?.incident_id === i.incident_id ? 'selected' : '')} onClick={() => setSelected(i.incident_id)}><span>{i.road_name.split(' · ')[0]}</span><strong>{i.risk.display}<small> /100</small></strong><b>{i.tag}</b><small>{i.independent_capture_count} capture{i.independent_capture_count === 1 ? '' : 's'} · {i.signal_ids.length} records</small><small>{i.evidence_strength} · {i.risk.risk_band}</small></button>)
  return <div className="app"><header><div className="brand"><span className="brand-mark">⋈</span><div><h1>Converge</h1><small>Municipal inspection workbench</small></div></div><div className="study">Nasr City <small>Phase 3 · real context integration</small></div><span className="demo-badge">{live ? 'Operator observations' : data.context_notice ? 'Synthetic replay · real geography' : data.mode === 'cached_extraction' ? 'Mixed-source demo' : 'Synthetic Demo'}</span><div className="clock"><b>{time(data.clock)}</b><small>Cairo · {live ? 'last computation' : 'synthetic replay clock'}</small></div><span className="mode">{live ? 'Local engine · text + image evidence' : data.mode === 'cached_extraction' ? 'Offline · cached AI image evidence' : 'Offline · reviewed inputs'}</span></header>
    <div className="toolbar"><button onClick={() => setShowObservations(!showObservations)}>{showObservations ? 'Hide observation workspace' : 'New observation'}</button><button onClick={() => setLive(!live)}>{live ? 'Show offline replay' : 'Show operator observations'}</button></div>
    {showObservations && <ObservationPanel onChanged={refreshLive}/>}
    {!live && <div className="toolbar"><div className="controls"><button disabled={busy || data.step > 0} onClick={() => replay('start')}>Start replay</button><button className="primary" disabled={busy || data.step === 0 || data.step >= data.total_steps} onClick={() => replay('advance')}>Advance</button><button disabled={busy} onClick={() => replay('reset')}>Reset</button></div><label>Scenario <select aria-label="Scenario" value={scenario} disabled={busy} onChange={e => setScenario(e.target.value)}>{['signature', 'signature_image', 'context_signature', 'context_archive', 'missing_road_damage', 'conflicting_water', 'spatial_119m', 'spatial_121m', 'time_5h59', 'time_6h', 'time_over_6h', 'chain_guard', 'road_incompatible'].map(s => <option value={s} key={s}>{human(s)}</option>)}</select></label><small>Reset loads the selected scenario.</small><div className="compare-controls"><label><input type="checkbox" checked={hideImage} disabled={busy || !data.step} onChange={e => compare(e.target.checked, copies)}/> Hide image evidence</label><label><input type="checkbox" checked={copies} disabled={busy || !data.step} onChange={e => compare(hideImage, e.target.checked)}/> Add 10 duplicates</label></div></div>}
    {data.context_notice && <div className="comparison" role="status">{data.context_notice}</div>}
    {error && <div className="error" role="alert">{error}</div>}
    {comparison && <div className="comparison" role="status">Sandbox comparison · {hideImage ? 'image family removed' : 'all families'} · {comparison.added_duplicates} added copies. Original replay remains intact.</div>}
    <main><aside className="queue"><div className="queue-heading"><h2>Inspection queue</h2><small>{incidents.filter(i => i.status === 'candidate').length} candidates</small></div>{queue('candidate')}<h3>Watch items</h3>{queue('watch')}{incidents.length === 0 && <p className="empty">{live ? "No admitted operator observations yet. Submit a report or review its admission exclusions." : "Start the replay to see the first observation. Independent evidence is required to form a candidate."}</p>}{data.excluded.length > 0 && <details><summary>{data.excluded.length} records excluded from active grouping</summary>{data.excluded.map(e => <p key={e.signal_id}>{e.signal_id}<small>{e.rule_ids.join(', ')}</small></p>)}</details>}<p className="queue-note">Inspection support. A human engineer verifies the physical cause.</p></aside>
      <MapPanel data={data} incidents={incidents} signals={signals} selected={chosen?.incident_id ?? null} onSelect={setSelected}/>
      {chosen ? <Detail incident={chosen} signals={signals}/> : <aside className="detail empty"><div className="eyebrow">Cross-signal incident intelligence</div><h2>Which location deserves inspection first?</h2><p>Follow the evidence as separate observations converge. Eight copied reports still count as one capture.</p><p>{live ? "Report claims and operator metadata feed the local engine. Physical conditions remain unverified." : data.context_notice ? data.context_notice : data.mode === 'cached_extraction' ? "This mixed-source replay uses one licensed public image with simulated placement/time; remaining records and all context are synthetic." : "All reports, annotations, rain and map segments in this replay are synthetic."}</p></aside>}
    </main><footer><div><b>Observation timeline</b><small>{live ? `Local computation ${data.step} · observation times below` : `Step ${data.step} / ${data.total_steps || '—'} · availability controls replay`}</small><progress max={data.total_steps || 1} value={data.step}/></div><ol className="timeline">{[...signals].sort((a, b) => a.observed_at.localeCompare(b.observed_at) || a.signal_id.localeCompare(b.signal_id)).map(s => <li key={s.signal_id}><button onClick={() => {const incident = incidents.find(i => i.signal_ids.includes(s.signal_id)); if (incident) setSelected(incident.incident_id)}} title={`Observed ${s.observed_at}; received ${s.received_at}; available ${s.available_at}`}><b>{time(s.observed_at)}</b><span>{s.signal_id}</span><small>{s.duplicate_of ? 'dependent copy' : s.source_family}</small></button></li>)}</ol></footer>
  </div>
}

createRoot(document.getElementById('root')!).render(<App/>)
