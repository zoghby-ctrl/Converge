import React from 'react'
import { navigate } from './router'

export function EntryGateway() {
  return (
    <div className="entry-viewport">
      <div className="entry-card">
        <div className="entry-brand-mark">⋈</div>
        <h1 className="entry-title">Converge</h1>
        <p className="entry-subtitle">
          Turn scattered urban signals into actionable incident intelligence.
        </p>

        <div className="entry-actions">
          <button
            id="entry-btn-report"
            className="btn-lg btn-primary"
            onClick={() => navigate('/report')}
          >
            <svg width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path d="M12 4v16m8-8H4" />
            </svg>
            Report an observation
          </button>
          <button
            id="entry-btn-operations"
            className="btn-lg btn-secondary"
            onClick={() => navigate('/operations')}
          >
            <svg width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
            </svg>
            Open operations
          </button>
        </div>

        <div className="entry-footer-meta">
          <span>Nasr City Study Prototype · IMPACTX 2026</span>
        </div>
      </div>
    </div>
  )
}
