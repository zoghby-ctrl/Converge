import React, {useEffect, useState} from 'react'

type State = 'present' | 'absent' | 'uncertain' | 'not_mentioned'
type Temporal = 'current' | 'resolved' | 'historical' | 'uncertain'
type Condition = 'standing_water' | 'road_damage' | 'passage_obstruction' | 'recurrence'
type Field = Condition | 'reported_duration' | 'reported_explanation' | 'temporal_status'
type Extraction = Record<Condition, State> & {
  language: string; temporal_status: Temporal; reported_duration: {minutes: number | null; phrase: string} | null;
  reported_explanation: string | null;
  evidence_spans: {field: Field; quote: string; temporal_status: Temporal}[];
  uncertainties: {field: Field; reason: string; affects_admission: boolean}[]
}
type Revision = {extraction: Extraction; source: string; model: string | null; model_identifier: string | null;
  fallback_used: boolean; fallback_reason: string | null; review_state: string; processed_at: string; revision: number}
type Job = {signal_id: string; original: {text: string; operator: string; content_origin: string}; status: string; error_code: string | null;
  revision: number; latest: Revision | null; revisions: Revision[]; disposition: string; excluded: {rule_ids: string[]}[]}
const conditions: Condition[] = ['standing_water', 'road_damage', 'passage_obstruction', 'recurrence']
const human = (s: string) => s.replaceAll('_', ' ')
const emptyExtraction: Extraction = {language: 'unknown', standing_water: 'not_mentioned', road_damage: 'not_mentioned',
  passage_obstruction: 'not_mentioned', recurrence: 'not_mentioned', reported_duration: null, reported_explanation: null,
  temporal_status: 'uncertain', evidence_spans: [], uncertainties: []}
const errorText: Record<string, string> = {
  invalid_api_key: 'OpenAI rejected the API key. Check the server .env; no automatic retry was made.',
  api_key_missing: 'Add the API key to the server .env and restart the backend.',
  api_unavailable: 'OpenAI is unreachable. Saved results and local replay remain available.',
  api_rate_or_credit_limit: 'OpenAI returned a rate or credit limit. Review the account before retrying.',
  model_unavailable: 'The configured model is unavailable to this API account.',
  api_configuration_rejected: 'OpenAI rejected the server request configuration.',
  fallback_disabled: 'Extraction requires review; Terra fallback is disabled.',
  development_usage_limit: 'The local development usage limit was reached. Cached and manual review remain available.',
  schema_invalid: 'Model output failed validation. No new evidence was admitted.',
  interrupted_restart: 'Processing was interrupted by a restart. Retry explicitly or review manually.'
}
async function api<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch('/api/v1/' + path, body ? {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)} : undefined)
  if (!r.ok) throw new Error(r.status === 409 ? 'The observation changed or is processing. Reload it before editing.' : `Request rejected (${r.status}). Check the fields and source quotes.`)
  return r.json()
}

function ReviewForm({job, saved}: {job: Job; saved: (job: Job) => void}) {
  const [value, setValue] = useState<Extraction>(structuredClone(job.latest?.extraction ?? emptyExtraction))
  const [reviewer, setReviewer] = useState(job.original.operator)
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  function change(field: Condition, state: State) {
    const next = structuredClone(value); next[field] = state
    next.uncertainties = next.uncertainties.filter(u => u.field !== field)
    if (state === 'not_mentioned') next.evidence_spans = next.evidence_spans.filter(s => s.field !== field)
    else if (!next.evidence_spans.some(s => s.field === field)) next.evidence_spans.push({field, quote: '', temporal_status: 'current'})
    if (state === 'uncertain') next.uncertainties.push({field, reason: 'ambiguous_wording', affects_admission: true})
    setValue(next)
  }
  function extra(field: 'reported_duration' | 'reported_explanation', content: string) {
    const next = structuredClone(value)
    if (field === 'reported_duration') next.reported_duration = content ? {phrase: content, minutes: next.reported_duration?.minutes ?? null} : null
    else next.reported_explanation = content || null
    if (!content) {next.evidence_spans = next.evidence_spans.filter(s => s.field !== field); next.uncertainties = next.uncertainties.filter(u => u.field !== field)}
    else if (!next.evidence_spans.some(s => s.field === field)) next.evidence_spans.push({field, quote: field === 'reported_duration' ? content : '', temporal_status: next.temporal_status})
    if (field === 'reported_duration') next.evidence_spans = next.evidence_spans.map(s => s.field === field ? {...s, quote: content} : s)
    setValue(next)
  }
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError('')
    try {saved(await api<Job>(`signals/${job.signal_id}/review`, {extraction: value, reviewer, reason, expected_revision: job.revision}))}
    catch (e) {setError(String(e))} finally {setBusy(false)}
  }
  return <form className="review-form" onSubmit={submit}><h3>Human correction · new revision</h3>
    <p>Quote the original report. Review confirms what the report says; it does not verify the physical condition.</p>
    <div className="observation-grid">{conditions.map(field => <label key={field}>{human(field)}<select aria-label={`Correct ${human(field)}`} value={value[field]} onChange={e => change(field, e.target.value as State)}>{['present', 'absent', 'uncertain', 'not_mentioned'].map(s => <option key={s}>{s}</option>)}</select></label>)}
      <label>Language<select value={value.language} onChange={e => setValue({...value, language: e.target.value})}>{['egyptian_arabic', 'standard_arabic', 'english', 'mixed', 'unknown'].map(s => <option key={s}>{s}</option>)}</select></label>
      <label>Episode time<select value={value.temporal_status} onChange={e => setValue({...value, temporal_status: e.target.value as Temporal})}>{['current', 'resolved', 'historical', 'uncertain'].map(s => <option key={s}>{s}</option>)}</select></label>
    </div>
    {value.evidence_spans.map((span, i) => <div className="observation-grid" key={i}><label>{human(span.field)} source quote<input required maxLength={180} value={span.quote} dir="auto" onChange={e => {const next = structuredClone(value); next.evidence_spans[i].quote = e.target.value; setValue(next)}}/></label><label>Claim time<select value={span.temporal_status} onChange={e => {const next = structuredClone(value); next.evidence_spans[i].temporal_status = e.target.value as Temporal; setValue(next)}}>{['current', 'resolved', 'historical', 'uncertain'].map(s => <option key={s}>{s}</option>)}</select></label></div>)}
    <details><summary>Duration, explanation and uncertainty</summary><p>These annotations do not establish persistence or verified cause.</p>
      <label>Duration phrase from report<input maxLength={120} value={value.reported_duration?.phrase ?? ''} onChange={e => extra('reported_duration', e.target.value)}/></label>
      {value.reported_duration && <label>Duration in minutes (leave empty if unquantified)<input type="number" min="0" max="5256000" value={value.reported_duration.minutes ?? ''} onChange={e => setValue({...value, reported_duration: {...value.reported_duration!, minutes: e.target.value === '' ? null : Number(e.target.value)}})}/></label>}
      <label>Reported explanation<input maxLength={240} value={value.reported_explanation ?? ''} onChange={e => extra('reported_explanation', e.target.value)}/></label>
      {value.uncertainties.map((u,i) => <p key={i}>{human(u.field)} · {human(u.reason)} <button type="button" onClick={() => setValue({...value, uncertainties: value.uncertainties.filter((_,n) => n !== i)})}>Remove resolved uncertainty</button></p>)}
    </details>
    <label>Reviewer<input required value={reviewer} maxLength={80} onChange={e => setReviewer(e.target.value)}/></label>
    <label>Correction reason<input required value={reason} maxLength={400} onChange={e => setReason(e.target.value)}/></label>
    <button disabled={busy || !reason.trim()} className="primary">Save reviewed revision</button>{error && <p role="alert">{error}</p>}
  </form>
}

export function ObservationPanel({onChanged}: {onChanged: () => void}) {
  const [jobs, setJobs] = useState<Job[]>([])
  const [job, setJob] = useState<Job | null>(null)
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [usage, setUsage] = useState<Record<string, unknown>>({})
  const [text, setText] = useState('')
  const [capture, setCapture] = useState<string>(crypto.randomUUID())
  const [submissionKey, setSubmissionKey] = useState<string>(crypto.randomUUID())
  const [independent, setIndependent] = useState(false)
  const [synthetic, setSynthetic] = useState(false)
  const [operator, setOperator] = useState('')
  const localNow = () => {const d = new Date(); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0,16)}
  const [observed, setObserved] = useState(localNow)
  const [lat, setLat] = useState('30.054')
  const [lon, setLon] = useState('31.336')
  const [road, setRoad] = useState('')
  const [accuracy, setAccuracy] = useState('10')
  async function refresh() {setJobs(await api<Job[]>('observations')); setUsage(await api<Record<string, unknown>>('perception/usage'))}
  useEffect(() => {refresh().catch(e => setError(String(e)))}, [])
  const running = job?.status === 'pending' || job?.status === 'analyzing'
  useEffect(() => {
    if (!job || !running) return
    let canceled = false
    const timer = setTimeout(async () => {
      try {const next = await api<Job>(`signals/${job.signal_id}/processing`); if (!canceled) {setJob(next); if (!['pending', 'analyzing'].includes(next.status)) {await refresh(); onChanged()}}}
      catch (e) {if (!canceled) setError(String(e))}
    }, 800)
    return () => {canceled = true; clearTimeout(timer)}
  }, [job, running, onChanged])
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(''); setEditing(false)
    try {
      const next = await api<Job>('signals', {text, lat: Number(lat), lon: Number(lon), observed_at: new Date(observed).toISOString(),
        location_accuracy_m: Number(accuracy), road_context_id: road, capture_group_id: capture,
        independence: independent ? 'asserted' : 'uncertain', operator, content_origin: synthetic ? 'synthetic' : 'collected', idempotency_key: submissionKey})
      setJob(next); setSubmissionKey(crypto.randomUUID()); setCapture(crypto.randomUUID()); await refresh(); onChanged()
    } catch (e) {setError(String(e))} finally {setBusy(false)}
  }
  async function reanalyze(action: string) {
    if (!job) return
    setBusy(true); setError(''); setEditing(false)
    try {setJob(await api<Job>(`signals/${job.signal_id}/reanalyze`, {action, expected_revision: job.revision}))}
    catch (e) {setError(String(e))} finally {setBusy(false)}
  }
  const x = job?.latest?.extraction
  return <section className="observation-panel" aria-label="Text observation workspace"><div className="observation-columns">
    <form onSubmit={submit}><h2>New observation</h2><label>Report text<textarea required maxLength={4000} rows={4} dir="auto" value={text} onChange={e => setText(e.target.value)}/></label>
      <div className="observation-grid"><label>Latitude<input required type="number" step="any" min="30.045" max="30.063" value={lat} onChange={e => setLat(e.target.value)}/></label><label>Longitude<input required type="number" step="any" min="31.325" max="31.346" value={lon} onChange={e => setLon(e.target.value)}/></label>
      <label>Observation time (device local)<input required type="datetime-local" value={observed} onChange={e => setObserved(e.target.value)}/></label><label>Location accuracy (m)<input required type="number" min="0" max="500" value={accuracy} onChange={e => setAccuracy(e.target.value)}/></label>
      <label>Reviewed road segment label<input required maxLength={80} value={road} onChange={e => setRoad(e.target.value)}/></label><label>Operator<input required maxLength={80} value={operator} onChange={e => setOperator(e.target.value)}/></label></div>
      <p className="muted">Confirm coordinates within the Nasr City study extent. Use the same segment label only for the same reviewed road. Road class and rainfall remain unknown.</p>
      <label>Capture group<input required maxLength={80} value={capture} onChange={e => setCapture(e.target.value)}/></label>
      <label className="inline-check"><input type="checkbox" checked={independent} onChange={e => setIndependent(e.target.checked)}/> I reviewed the source and assert this capture is independent; copies share a capture group.</label>
      <label className="inline-check"><input type="checkbox" checked={synthetic} onChange={e => setSynthetic(e.target.checked)}/> This is a synthetic test report with simulated placement and time.</label>
      <button className="primary" disabled={busy || running || !text.trim() || !operator.trim() || !road.trim()}>Submit for text analysis</button><p className="muted">Analysis runs only on submission or an explicit review action.</p>
    </form>
    <div><h2>Extraction and review</h2><label>Saved observation<select aria-label="Saved observation" value={job?.signal_id ?? ''} onChange={async e => {if (!e.target.value) return; setJob(await api<Job>(`signals/${e.target.value}/processing`)); setEditing(false)}}><option value="">Select a saved report</option>{jobs.map(j => <option key={j.signal_id} value={j.signal_id}>{j.original.text.slice(0,45)} · {human(j.status)}</option>)}</select></label>
      {job && <article className="extraction"><p role="status"><b>{human(job.status).replace(/^./, s => s.toUpperCase())}</b> · revision {job.revision}</p>
        {job.error_code && <p role="alert">{errorText[job.error_code] ?? 'Processing failed. Review manually or retry explicitly.'}</p>}
        <h3>Original report</h3><small>{job.original.content_origin === 'synthetic' ? 'Synthetic test · simulated placement and time' : 'Operator-supplied report and metadata'}</small><blockquote dir="auto">{job.original.text}</blockquote>
        {job.latest && <><p><b>{job.latest.source === 'manual' ? 'Human reviewed' : job.latest.source === 'cached' ? 'Cached AI extraction' : 'Live AI extraction'}</b> · {job.latest.model ?? 'operator'}<br/><small>Produced {new Date(job.latest.processed_at).toLocaleString()} · {human(job.latest.review_state)}</small></p>
          {job.latest.fallback_used && <p className="fallback-note">Terra fallback used: {human(job.latest.fallback_reason ?? '')}. Primary output is retained in revision details.</p>}
          {x && <><p>Language: {human(x.language)} · episode: {x.temporal_status}</p><table><tbody>{conditions.map(f => <tr key={f}><th>{human(f)}</th><td><b>{x[f].toUpperCase()}</b>{x.evidence_spans.filter(s => s.field === f).map((s, i) => <p key={i} dir="auto">“{s.quote}” <small>({s.temporal_status})</small></p>)}</td></tr>)}<tr><th>Duration</th><td>{x.reported_duration ? `${x.reported_duration.minutes === null ? 'Unquantified' : '~' + x.reported_duration.minutes + ' minutes'} · “${x.reported_duration.phrase}”` : 'Not mentioned'}</td></tr><tr><th>Reported explanation</th><td>{x.reported_explanation ?? 'None'}<small>Reporter claim; never verified cause.</small></td></tr></tbody></table>{x.uncertainties.map((u,i) => <p key={i}>{human(u.field)}: {human(u.reason)}{u.affects_admission ? ' · admission uncertain' : ''}</p>)}</>}
          <details><summary>Revision history and provenance ({job.revisions.length})</summary><pre>{JSON.stringify(job.revisions, null, 2)}</pre></details></>}
        <p><b>Engine result: {human(job.disposition)}</b></p>{job.disposition === 'not_admitted' && <p>{job.excluded.flatMap(e => e.rule_ids).map(human).join('; ') || 'No admitted extraction yet.'}</p>}
        {!running && <div className="review-actions"><button disabled={busy} onClick={() => setEditing(!editing)}>Correct extraction</button><button disabled={busy} onClick={() => reanalyze('retry_primary')}>Retry primary / use cache</button><button disabled={busy} onClick={() => reanalyze('deeper_review')}>Deeper review with Terra</button></div>}
        {editing && <ReviewForm key={job.signal_id + ':' + job.revision} job={job} saved={next => {setJob(next); setEditing(false); refresh().catch(e => setError(String(e))); onChanged()}}/>}
      </article>}
    </div></div>{error && <p className="error" role="alert">{error}</p>}
    <details><summary>Local API usage</summary><pre>{JSON.stringify(usage, null, 2)}</pre></details>
  </section>
}
