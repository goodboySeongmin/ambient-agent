import { useEffect, useMemo, useState } from 'react'
import './App.css'

const API_BASE = 'http://localhost:8000'
const POLL_INTERVAL_MS = 3000

const FEEDBACK_LABELS = {
  accepted: 'Accepted',
  dismissed: 'Dismissed',
  helpful: 'Helpful',
  not_helpful: 'Not Helpful',
}

const FEEDBACK_ICONS = {
  accepted: '✓',
  dismissed: '×',
  helpful: '♥',
  not_helpful: '−',
}

function clamp(value) {
  const number = Number(value ?? 0)
  return Math.max(0, Math.min(1, number))
}

function percent(value) {
  return `${Math.round(clamp(value) * 100)}%`
}

function score(value) {
  return Number(value ?? 0).toFixed(3)
}

function formatTime(value) {
  if (!value) return '—'

  const date = new Date(value)

  if (Number.isNaN(date.getTime())) {
    return '—'
  }

  return new Intl.DateTimeFormat('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
}

function humanize(value) {
  if (!value) return 'Unknown'

  return String(value)
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function ScoreRing({ value, label }) {
  const normalized = clamp(value)
  const degrees = normalized * 360

  return (
    <div
      className="score-ring"
      style={{
        '--score-angle': `${degrees}deg`,
      }}
    >
      <div className="score-ring-inner">
        <strong>{percent(normalized)}</strong>
        <span>{label}</span>
      </div>
    </div>
  )
}

function SignalBar({ label, value }) {
  const normalized = clamp(value)

  return (
    <div className="signal-row">
      <div className="signal-meta">
        <span>{label}</span>
        <strong>{percent(normalized)}</strong>
      </div>

      <div className="signal-track">
        <div
          className="signal-fill"
          style={{
            width: `${normalized * 100}%`,
          }}
        />
      </div>
    </div>
  )
}

function StatusBadge({ children, tone = 'neutral' }) {
  return (
    <span className={`status-badge ${tone}`}>
      <span className="status-badge-dot" />
      {children}
    </span>
  )
}

function App() {
  const [context, setContext] = useState(null)
  const [stuck, setStuck] = useState(null)
  const [intervention, setIntervention] = useState(null)
  const [feedback, setFeedback] = useState([])
  const [lastUpdated, setLastUpdated] = useState(null)
  const [loading, setLoading] = useState(true)
  const [apiOnline, setApiOnline] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let mounted = true
    let timer = null

    async function loadDashboard() {
      try {
        const [
          contextResponse,
          stuckResponse,
          interventionResponse,
          feedbackResponse,
        ] = await Promise.all([
          fetch(`${API_BASE}/sessions/current/context`),
          fetch(`${API_BASE}/sessions/current/stuck-signal`),
          fetch(`${API_BASE}/sessions/current/intervention`),
          fetch(`${API_BASE}/sessions/current/feedback-history?limit=8`),
        ])

        const responses = [
          contextResponse,
          stuckResponse,
          interventionResponse,
          feedbackResponse,
        ]

        const failedResponse = responses.find(
          (response) => !response.ok,
        )

        if (failedResponse) {
          throw new Error(
            `API request failed: ${failedResponse.status}`,
          )
        }

        const [
          contextData,
          stuckData,
          interventionData,
          feedbackData,
        ] = await Promise.all([
          contextResponse.json(),
          stuckResponse.json(),
          interventionResponse.json(),
          feedbackResponse.json(),
        ])

        if (!mounted) return

        setContext(contextData)
        setStuck(stuckData)
        setIntervention(interventionData)
        setFeedback(feedbackData.items ?? [])
        setLastUpdated(new Date())
        setApiOnline(true)
        setError(null)
      } catch (requestError) {
        if (!mounted) return

        console.error(requestError)
        setApiOnline(false)
        setError(requestError.message)
      } finally {
        if (mounted) {
          setLoading(false)
        }
      }
    }

    loadDashboard()

    timer = window.setInterval(
      loadDashboard,
      POLL_INTERVAL_MS,
    )

    return () => {
      mounted = false

      if (timer) {
        window.clearInterval(timer)
      }
    }
  }, [])

  const signals = useMemo(() => {
    const raw = stuck?.signals ?? {}

    return [
      ['Search Repeat', raw.search_repeat],
      ['Search Revisit', raw.search_revisit],
      ['Semantic Loop', raw.semantic_loop],
      ['Rapid Switch', raw.rapid_switch],
      ['Duration', raw.duration],
    ]
  }, [stuck])

  const interventionTone = intervention?.should_intervene
    ? 'danger'
    : intervention?.suppressed
      ? 'warning'
      : 'success'

  const stateTone =
    context?.state === 'debugging'
      ? 'danger'
      : context?.state === 'unknown'
        ? 'neutral'
        : 'info'

  const recentAccepted = feedback.filter(
    (item) => item.feedback_type === 'accepted',
  ).length

  const recentDismissed = feedback.filter(
    (item) => item.feedback_type === 'dismissed',
  ).length

  const recentHelpful = feedback.filter(
    (item) => item.feedback_type === 'helpful',
  ).length

  const recentNotHelpful = feedback.filter(
    (item) => item.feedback_type === 'not_helpful',
  ).length

  return (
    <main className="dashboard-shell">
      <header className="topbar">
        <div className="brand">
          <div className="ambient-mark">
            <div className="ambient-mark-core" />
          </div>

          <div>
            <div className="brand-row">
              <h1>Ambient Agent</h1>
              <span className="version">MVP · 01</span>
            </div>

            <p>
              The AI that notices when you're stuck
            </p>
          </div>
        </div>

        <div className="live-area">
          <div className={`live-indicator ${apiOnline ? 'online' : 'offline'}`}>
            <span className="live-dot" />
            {apiOnline ? 'LIVE' : 'OFFLINE'}
          </div>

          <span className="updated-at">
            {lastUpdated
              ? `Updated ${formatTime(lastUpdated)}`
              : 'Waiting for data'}
          </span>
        </div>
      </header>

      {error && (
        <div className="error-banner">
          <strong>Backend connection lost.</strong>
          <span>{error}</span>
        </div>
      )}

      <section className="pipeline-strip">
        <div className="pipeline-node active">
          <span>01</span>
          <strong>OBSERVE</strong>
        </div>
        <div className="pipeline-line" />
        <div className="pipeline-node active">
          <span>02</span>
          <strong>UNDERSTAND</strong>
        </div>
        <div className="pipeline-line" />
        <div className="pipeline-node active">
          <span>03</span>
          <strong>DETECT</strong>
        </div>
        <div className="pipeline-line" />
        <div className="pipeline-node active">
          <span>04</span>
          <strong>DECIDE</strong>
        </div>
        <div className="pipeline-line" />
        <div className="pipeline-node active">
          <span>05</span>
          <strong>LEARN</strong>
        </div>
      </section>

      {loading ? (
        <section className="loading-panel">
          <div className="loading-orb" />
          <strong>Connecting to Ambient Agent</strong>
          <span>Reading current cognitive state...</span>
        </section>
      ) : (
        <>
          <section className="dashboard-grid">
            <article className="panel context-panel">
              <div className="panel-header">
                <div>
                  <span className="eyebrow">
                    01 · SEMANTIC REASONING
                  </span>
                  <h2>Current Context</h2>
                </div>

                <StatusBadge tone={stateTone}>
                  {humanize(context?.state)}
                </StatusBadge>
              </div>

              <div className="context-summary">
                <span>AI INTERPRETATION</span>
                <p>
                  {context?.summary ??
                    'No semantic context available.'}
                </p>
              </div>

              <div className="context-fields">
                <div className="context-field">
                  <span>GOAL</span>
                  <strong>
                    {context?.goal ?? 'Not inferred yet'}
                  </strong>
                </div>

                <div className="context-field">
                  <span>CURRENT TASK</span>
                  <strong>
                    {context?.task ?? 'Not inferred yet'}
                  </strong>
                </div>

                <div className="context-field blocker-field">
                  <span>BLOCKER</span>
                  <strong>
                    {context?.blocker ??
                      'No explicit blocker detected'}
                  </strong>
                </div>
              </div>

              <div className="confidence-row">
                <div>
                  <span>CONTEXT CONFIDENCE</span>
                  <strong>{percent(context?.confidence)}</strong>
                </div>

                <div className="confidence-track">
                  <div
                    className="confidence-fill"
                    style={{
                      width: percent(context?.confidence),
                    }}
                  />
                </div>
              </div>
            </article>

            <article className="panel stuck-panel">
              <div className="panel-header">
                <div>
                  <span className="eyebrow">
                    02 · TEMPORAL BEHAVIOR
                  </span>
                  <h2>Stuck Detection</h2>
                </div>

                <StatusBadge
                  tone={
                    stuck?.stuck_level === 'high'
                      ? 'danger'
                      : stuck?.stuck_level === 'medium'
                        ? 'warning'
                        : 'success'
                  }
                >
                  {humanize(stuck?.stuck_level)}
                </StatusBadge>
              </div>

              <div className="stuck-main">
                <ScoreRing
                  value={stuck?.stuck_score}
                  label="STUCK SCORE"
                />

                <div className="stuck-diagnostics">
                  <div>
                    <span>SESSION</span>
                    <strong>
                      #{stuck?.session_id ?? '—'}
                    </strong>
                  </div>

                  <div>
                    <span>ACTIVITIES</span>
                    <strong>
                      {stuck?.diagnostics?.activity_count ?? 0}
                    </strong>
                  </div>

                  <div>
                    <span>RAPID SWITCHES</span>
                    <strong>
                      {stuck?.diagnostics?.rapid_switch_count ?? 0}
                    </strong>
                  </div>

                  <div>
                    <span>SEARCHES</span>
                    <strong>
                      {stuck?.diagnostics?.search_count ?? 0}
                    </strong>
                  </div>
                </div>
              </div>

              <div className="signals">
                {signals.map(([label, value]) => (
                  <SignalBar
                    key={label}
                    label={label}
                    value={value}
                  />
                ))}
              </div>

              <div className="reason-box">
                <span>DETECTED EVIDENCE</span>

                {stuck?.reasons?.length ? (
                  stuck.reasons.map((reason) => (
                    <p key={reason}>{reason}</p>
                  ))
                ) : (
                  <p>No meaningful stuck signals detected.</p>
                )}
              </div>
            </article>

            <article className="panel intervention-panel">
              <div className="panel-header">
                <div>
                  <span className="eyebrow">
                    03 · INTERVENTION POLICY
                  </span>
                  <h2>Decision Engine</h2>
                </div>

                <StatusBadge tone={interventionTone}>
                  {intervention?.should_intervene
                    ? 'Intervene'
                    : intervention?.suppressed
                      ? 'Suppressed'
                      : 'Observe'}
                </StatusBadge>
              </div>

              <div className="decision-layout">
                <ScoreRing
                  value={intervention?.intervention_score}
                  label="POLICY SCORE"
                />

                <div className="decision-copy">
                  <span className="decision-label">
                    CURRENT DECISION
                  </span>

                  <strong className="decision-title">
                    {intervention?.should_intervene
                      ? 'Offer proactive help'
                      : intervention?.suppressed
                        ? 'Respect user dismissal'
                        : 'Do not interrupt'}
                  </strong>

                  <p>
                    {intervention?.reason ??
                      'No policy decision available.'}
                  </p>
                </div>
              </div>

              <div className="component-grid">
                <div>
                  <span>NEED</span>
                  <strong>
                    {score(intervention?.components?.need)}
                  </strong>
                </div>

                <div>
                  <span>CONFIDENCE</span>
                  <strong>
                    {score(intervention?.components?.confidence)}
                  </strong>
                </div>

                <div>
                  <span>TASK CLARITY</span>
                  <strong>
                    {score(intervention?.components?.task_clarity)}
                  </strong>
                </div>

                <div>
                  <span>BLOCKER</span>
                  <strong>
                    {score(intervention?.components?.blocker)}
                  </strong>
                </div>

                <div>
                  <span>INTERRUPTION COST</span>
                  <strong>
                    {score(intervention?.components?.interruption_cost)}
                  </strong>
                </div>
              </div>

              <div className="action-box">
                <span>RECOMMENDED ACTION</span>
                <strong>
                  {intervention?.recommended_action ??
                    'Continue passive observation'}
                </strong>
              </div>

              {intervention?.suppressed && (
                <div className="suppression-box">
                  User preference suppression ·{' '}
                  {humanize(
                    intervention?.suppression_reason,
                  )}
                </div>
              )}
            </article>

            <article className="panel feedback-panel">
              <div className="panel-header">
                <div>
                  <span className="eyebrow">
                    04 · HUMAN FEEDBACK
                  </span>
                  <h2>Learning Signal</h2>
                </div>

                <span className="feedback-count">
                  {feedback.length} RECENT
                </span>
              </div>

              <div className="feedback-stats">
                <div>
                  <strong>{recentAccepted}</strong>
                  <span>Accepted</span>
                </div>

                <div>
                  <strong>{recentHelpful}</strong>
                  <span>Helpful</span>
                </div>

                <div>
                  <strong>{recentDismissed}</strong>
                  <span>Dismissed</span>
                </div>

                <div>
                  <strong>{recentNotHelpful}</strong>
                  <span>Not Helpful</span>
                </div>
              </div>

              <div className="feedback-list">
                {feedback.length === 0 ? (
                  <div className="empty-feedback">
                    No feedback collected in this session.
                  </div>
                ) : (
                  feedback.map((item) => (
                    <div
                      className={`feedback-item ${item.feedback_type}`}
                      key={item.id}
                    >
                      <div className="feedback-icon">
                        {FEEDBACK_ICONS[item.feedback_type] ??
                          '•'}
                      </div>

                      <div className="feedback-content">
                        <div>
                          <strong>
                            {FEEDBACK_LABELS[
                              item.feedback_type
                            ] ?? item.feedback_type}
                          </strong>

                          <time>
                            {formatTime(item.created_at)}
                          </time>
                        </div>

                        <p>
                          {item.goal ??
                            item.task ??
                            'Context unavailable'}
                        </p>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </article>
          </section>

          <footer className="system-footer">
            <div>
              <span className="footer-dot" />
              Browser activity
            </div>

            <span>→</span>

            <div>Behavior features</div>

            <span>→</span>

            <div>Qwen context reasoning</div>

            <span>→</span>

            <div>Intervention policy</div>

            <span>→</span>

            <div>Human feedback</div>
          </footer>
        </>
      )}
    </main>
  )
}

export default App
