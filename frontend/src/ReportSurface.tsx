import { UPLOAD_LIMIT_MB } from './uploadLimit'
import React, { useState, useEffect, useRef } from 'react'
import { navigate } from './router'

interface RoadMatchResult {
  road_context_id: string | null
  reason: string
  distance_m?: number
  matched_point?: [number, number]
}

const STUDY_BOUNDS = {
  minLat: 30.045,
  maxLat: 30.063,
  minLon: 31.325,
  maxLon: 31.346,
}

const STUDY_PRESETS = [
  { name: 'Street 14', lat: 30.054, lon: 31.336 },
  { name: 'Al-Tayaran', lat: 30.057, lon: 31.331 },
  { name: 'Youssef Abbas', lat: 30.059, lon: 31.334 },
]

function isInsideStudyArea(lat: number, lon: number): boolean {
  return lat >= STUDY_BOUNDS.minLat && lat <= STUDY_BOUNDS.maxLat && lon >= STUDY_BOUNDS.minLon && lon <= STUDY_BOUNDS.maxLon
}

export function ReportSurface() {
  const locationChosen = useRef(false)
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState('')
  
  // Geolocation & Fallback
  const [lat, setLat] = useState(0)
  const [lon, setLon] = useState(0)
  const [accuracy, setAccuracy] = useState<number | null>(null)
  const [matchedRoad, setMatchedRoad] = useState<string | null>(null)
  const [roadLabel, setRoadLabel] = useState('')
  const [showLocationEdit, setShowLocationEdit] = useState(true)
  const [locationSource, setLocationSource] = useState<'unavailable' | 'detected_gps' | 'preset' | 'manual'>('unavailable')
  const [locationConfirmed, setLocationConfirmed] = useState(false)
  
  // Time selector
  const [timeChoice, setTimeChoice] = useState<'just_now' | '15m_ago' | 'earlier'>('just_now')
  
  // State handling
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [submittedSignalId, setSubmittedSignalId] = useState<string | null>(null)
  const [submittedTimestamp, setSubmittedTimestamp] = useState<string | null>(null)

  // Resolve road match via backend if available
  useEffect(() => {
    let active = true
    setMatchedRoad(null)
    if (accuracy === null || locationSource !== 'detected_gps') return
    fetch(`/api/v1/context/road-match?lon=${lon}&lat=${lat}&accuracy_m=${accuracy}`)
      .then(res => res.ok ? res.json() : null)
      .then((data: RoadMatchResult | null) => {
        if (!active) return
        if (data?.road_context_id) {
          setMatchedRoad(data.road_context_id)
          setRoadLabel(data.road_context_id.replace(/^way-/, 'Way ').replaceAll('_', ' '))
        } else {
          setMatchedRoad(null)
        }
      })
      .catch(() => {
        if (active) setMatchedRoad(null)
      })
    return () => { active = false }
  }, [lat, lon, accuracy, locationSource])

  // Optional HTML5 geolocation attempt on mount (Constraint 3: never silently substitute Street 14)
  useEffect(() => {
    let active = true
    if ('geolocation' in navigator) {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          if (!active || locationChosen.current) return
          const userLat = pos.coords.latitude
          const userLon = pos.coords.longitude
          const userAccuracy = pos.coords.accuracy
          setLat(userLat)
          setLon(userLon)
          setAccuracy(userAccuracy)
          setLocationSource('detected_gps')
          if (!isInsideStudyArea(userLat, userLon)) {
            setShowLocationEdit(true)
          }
        },
        () => {
          if (active) setError('Location unavailable. Choose a SIMULATED demo placement or enter and confirm coordinates.')
        },
        { timeout: 4000 }
      )
    }
    return () => { active = false }
  }, [])

  // Manage photo preview URL
  useEffect(() => {
    if (!file) {
      setPreview('')
      return
    }
    const url = URL.createObjectURL(file)
    setPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const chosen = e.target.files?.[0] ?? null
    setError('')
    if (!chosen) {
      setFile(null)
      return
    }
    if (!['image/jpeg', 'image/png'].includes(chosen.type)) {
      setError('Only JPEG and PNG images are accepted.')
      setFile(null)
      return
    }
    if (chosen.size > UPLOAD_LIMIT_MB * 1024 * 1024) {
      setError(`Photo must be smaller than ${UPLOAD_LIMIT_MB} MB.`)
      setFile(null)
      return
    }
    setFile(chosen)
  }

  function calculateObservedAt(): string {
    const now = new Date()
    if (timeChoice === '15m_ago') {
      return new Date(now.getTime() - 15 * 60000).toISOString()
    }
    if (timeChoice === 'earlier') {
      return new Date(now.getTime() - 60 * 60000).toISOString()
    }
    return now.toISOString()
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!text.trim() && !file) {
      setError('Please describe what you observed or attach a photo.')
      return
    }
    if (!locationConfirmed) { setError('Choose or confirm the submission location.'); return }
    if (!isInsideStudyArea(lat, lon)) {
      setError(`Coordinates (${lat}°, ${lon}°) are outside the active Nasr City study area (30.045°–30.063° N, 31.325°–31.346° E). Please select a study location preset or adjust coordinates before sending.`)
      return
    }
    setBusy(true)
    setError('')

    const captureGroupId = 'cg-' + crypto.randomUUID().slice(0, 8)
    const idempotencyKey = 'rep-' + crypto.randomUUID().slice(0, 12)
    const effectiveRoad = locationSource === 'detected_gps' ? matchedRoad : null
    const observedAt = calculateObservedAt()

    const metadata = {
      text: text.trim() || null,
      lat,
      lon,
      observed_at: observedAt,
      location_accuracy_m: accuracy,
      road_context_id: effectiveRoad,
      capture_group_id: captureGroupId,
      independence: 'uncertain',
      operator: 'Citizen report',
      content_origin: locationSource === 'detected_gps' ? 'collected' : 'synthetic',
      idempotency_key: idempotencyKey
    }

    try {
      let signalId = ''
      if (file) {
        // Multipart image upload with linked text in one submission (Constraint 3)
        const formData = new FormData()
        formData.append('image', file)
        formData.append('metadata', JSON.stringify(metadata))
        const res = await fetch('/api/v1/images', { method: 'POST', body: formData })
        if (!res.ok) {
          const body = await res.json().catch(() => ({}))
          throw new Error(body.detail || `Upload rejected (${res.status})`)
        }
        const data = await res.json()
        signalId = data.signal_id || data.image_job?.signal_id || 'sig-' + crypto.randomUUID().slice(0, 6)
      } else {
        // Text observation
        const res = await fetch('/api/v1/signals', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...metadata, text: text.trim() })
        })
        if (!res.ok) {
          const body = await res.json().catch(() => ({}))
          throw new Error(body.detail || `Submission rejected (${res.status})`)
        }
        const data = await res.json()
        signalId = data.signal_id || 'sig-' + crypto.randomUUID().slice(0, 6)
      }

      setSubmittedSignalId(signalId)
      setSubmittedTimestamp(new Intl.DateTimeFormat('en-GB', {
        timeZone: 'Africa/Cairo',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
      }).format(new Date()))
    } catch (err: any) {
      const isOffline = (typeof navigator !== 'undefined' && !navigator.onLine) || (err instanceof TypeError && /failed to fetch|network|load/i.test(err.message))
      if (isOffline) {
        setError('Offline: Report was NOT sent. Your entered text and photo are preserved. You can retry sending once your connection is restored.')
      } else {
        setError(String(err instanceof Error ? err.message : err))
      }
    } finally {
      setBusy(false)
    }
  }

  function handleReset() {
    setText('')
    setFile(null)
    setSubmittedSignalId(null)
    setError('')
  }

  return (
    <div className="report-viewport">
      <header className="report-top-bar">
        <button className="report-back-btn" onClick={() => navigate('/')} aria-label="Return home">
          ⋈ <span style={{ marginLeft: 4 }}>Converge</span>
        </button>
        <span className="report-header-title">Report an Observation</span>
        <button className="report-ops-link" onClick={() => navigate('/operations')}>
          Operations ➔
        </button>
      </header>

      <main className="report-content-area">
        {submittedSignalId ? (
          /* Receipt Screen */
          <div className="report-receipt-card" role="status">
            <div className="receipt-check-glyph">✓</div>
            <h2 className="receipt-heading">Observation registered</h2>
            <p className="receipt-message">
              Your observation has been registered. Registration does not mean completed analysis or admission as independent evidence.
            </p>
            <div className="receipt-meta-box">
              <span>Time: {submittedTimestamp} Cairo</span>
              <span>Location: {matchedRoad ? roadLabel : `${lat}° N, ${lon}° E`}</span>
            </div>
            <details><summary>Observation reference</summary><code>{submittedSignalId}</code></details>
            <div className="receipt-actions">
              <button className="btn-lg btn-primary" onClick={handleReset}>
                Submit another observation
              </button>
              <button className="btn-lg btn-secondary" onClick={() => navigate('/operations')}>
                Open operations workbench
              </button>
            </div>
          </div>
        ) : (
          /* Submission Form */
          <form className="report-form" onSubmit={handleSubmit}>
            {error && <div className="report-error-banner" role="alert">{error}</div>}

            <div className="form-group">
              <label htmlFor="report-desc" className="form-label">What do you see?</label>
              <span className="form-hint">Describe standing water, road deterioration, or passage obstruction.</span>
              <textarea
                id="report-desc"
                className="form-textarea"
                rows={3}
                dir="auto"
                value={text}
                onChange={e => setText(e.target.value)}
                placeholder="e.g. مياه متراكمة في الحارة اليمين وكسر في الأسفلت"
                required={!file}
              />
            </div>

            <div className="form-group">
              <label className="form-label">Add a photo (optional)</label>
              {preview ? (
                <div className="photo-preview-box">
                  <img src={preview} alt="Attached observation preview" />
                  <div className="photo-preview-actions">
                    <span className="photo-file-size">{(file!.size / (1024 * 1024)).toFixed(2)} MB</span>
                    <button type="button" className="btn-sm" onClick={() => setFile(null)}>Remove photo</button>
                  </div>
                </div>
              ) : (
                <label className="photo-dropzone">
                  <input
                    type="file"
                    accept="image/jpeg,image/png"
                    onChange={handleFileChange}
                    style={{ display: 'none' }}
                  />
                  <div className="photo-dropzone-inner">
                    <span className="photo-camera-icon">📷</span>
                    <span className="photo-dropzone-prompt">Take photo or choose from library</span>
                  </div>
                </label>
              )}
              <span className="form-privacy-note">Photo metadata is removed for privacy.</span>
            </div>

            <div className="form-group">
              <label className="form-label">Location</label>

              {!isInsideStudyArea(lat, lon) && (
                <div className="report-out-of-area-banner" role="alert">
                  <strong>{locationSource === 'unavailable' ? 'Choose a location:' : 'Location outside study area:'}</strong>
                  <p style={{ margin: '4px 0' }}>
                    {locationSource === 'unavailable' ? 'GPS unavailable or pending. No submission location has been selected.' : `Coordinates (${lat}° N, ${lon}° E) are outside the active Nasr City coverage area (30.045°–30.063° N, 31.325°–31.346° E).`}
                  </p>
                  <div className="preset-buttons-row">
                    <span>Choose a SIMULATED demo placement:</span>
                    {STUDY_PRESETS.map(preset => (
                      <button
                        key={preset.name}
                        type="button"
                        className="btn-preset"
                        onClick={() => {
                          setLat(preset.lat)
                          setLon(preset.lon)
                          setRoadLabel(preset.name)
                          locationChosen.current = true; setLocationSource('preset'); setAccuracy(null); setMatchedRoad(null); setLocationConfirmed(true)
                          setError('')
                        }}
                      >
                        {preset.name}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <p>{locationSource === 'unavailable' ? 'No location selected.' : locationSource === 'detected_gps' ? `GPS accuracy: ${accuracy} m` : 'SIMULATED / DEMO PLACEMENT — no GPS accuracy; excluded from independent evidence.'}</p>
              <p>{matchedRoad ? 'Bounded road match available.' : 'Road context unknown / unverified.'}</p>
              <label><input type="checkbox" checked={locationConfirmed} disabled={locationSource === 'unavailable'} onChange={e => setLocationConfirmed(e.target.checked)} /> I confirm these coordinates for submission</label>
              <div className="location-pill-card">
                <div className="loc-info">
                  <span className="loc-title">
                    {locationSource === 'unavailable' ? 'No location selected' : isInsideStudyArea(lat, lon)
                      ? (locationSource === 'detected_gps' ? 'GPS location' : 'SIMULATED / DEMO PLACEMENT')
                      : 'Location outside study area'}
                  </span>
                  <span className="loc-subtitle" style={!isInsideStudyArea(lat, lon) ? { color: '#B45309' } : undefined}>
                    {locationSource === 'unavailable' ? 'No location selected' : isInsideStudyArea(lat, lon)
                      ? (matchedRoad ? `${roadLabel} (bounded road match)` : `${lat}° N, ${lon}° E (Study area)`)
                      : `${lat}° N, ${lon}° E (Adjustment required)`}
                  </span>
                </div>
                <button
                  type="button"
                  className="btn-sm"
                  onClick={() => setShowLocationEdit(!showLocationEdit)}
                >
                  {showLocationEdit ? 'Done' : 'Change'}
                </button>
              </div>

              {showLocationEdit && (
                <div className="location-edit-drawer">
                  <div className="location-coords-row">
                    <label className="form-sublabel">
                      Lat
                      <input
                        type="number"
                        step="0.001"
                        min="30.045"
                        max="30.063"
                        className="form-input"
                        value={lat}
                        onChange={e => { setLat(Number(e.target.value)); setAccuracy(null); setMatchedRoad(null); locationChosen.current = true; setLocationSource('manual'); setLocationConfirmed(false) }}
                      />
                    </label>
                    <label className="form-sublabel">
                      Lon
                      <input
                        type="number"
                        step="0.001"
                        min="31.325"
                        max="31.346"
                        className="form-input"
                        value={lon}
                        onChange={e => { setLon(Number(e.target.value)); setAccuracy(null); setMatchedRoad(null); locationChosen.current = true; setLocationSource('manual'); setLocationConfirmed(false) }}
                      />
                    </label>
                  </div>
                  {isInsideStudyArea(lat, lon) && (
                    <div className="preset-buttons-row">
                      <span>SIMULATED demo presets:</span>
                      {STUDY_PRESETS.map(preset => (
                        <button
                          key={preset.name}
                          type="button"
                          className="btn-preset"
                          onClick={() => {
                            setLat(preset.lat)
                            setLon(preset.lon)
                            setRoadLabel(preset.name)
                            locationChosen.current = true; setLocationSource('preset'); setAccuracy(null); setMatchedRoad(null); setLocationConfirmed(true)
                          }}
                        >
                          {preset.name}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="form-group">
              <label className="form-label">When was this observed?</label>
              <div className="time-chips-group">
                <button
                  type="button"
                  className={`time-chip ${timeChoice === 'just_now' ? 'active' : ''}`}
                  onClick={() => setTimeChoice('just_now')}
                >
                  Just now
                </button>
                <button
                  type="button"
                  className={`time-chip ${timeChoice === '15m_ago' ? 'active' : ''}`}
                  onClick={() => setTimeChoice('15m_ago')}
                >
                  15m ago
                </button>
                <button
                  type="button"
                  className={`time-chip ${timeChoice === 'earlier' ? 'active' : ''}`}
                  onClick={() => setTimeChoice('earlier')}
                >
                  About 1 hour ago
                </button>
              </div>
            </div>

            <button
              id="report-submit-btn"
              type="submit"
              className="btn-lg btn-primary report-submit-btn"
              disabled={!locationConfirmed || busy || (!text.trim() && !file) || !isInsideStudyArea(lat, lon)}
            >
              {busy
                ? 'Registering signal…'
                : (!isInsideStudyArea(lat, lon)
                  ? 'Adjust location to send'
                  : (error.startsWith('Offline:') ? 'Retry sending observation' : 'Send observation'))}
            </button>

            <p className="report-disclaimer">
              Reports are registered as observational signals for municipal engineering.
            </p>
          </form>
        )}
      </main>
    </div>
  )
}
