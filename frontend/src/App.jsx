import { useEffect, useRef, useState } from 'react'
import './App.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// ─── palette: Ocean Depths (theme-factory) ──────────────────────────────────
// bg cream #f1faee · card white · primary navy #1a2332 · accent teal #2d8b8b
// teal text-step #1f6f6f · seafoam #a8dadc · text #0F172A · secondary #64748B
// status: success #16A34A · warning #D97706 · danger #DC2626 (text steps darker)

// ─── helpers ────────────────────────────────────────────────────────────────

function getConfidenceStyle(confidence) {
  // Text steps are darker than the fill hues so 12px badge text clears WCAG AA (4.5:1).
  if (confidence >= 0.7) return 'bg-[#16A34A]/10 text-[#15803D] border-[#16A34A]/30'
  if (confidence >= 0.4) return 'bg-[#D97706]/10 text-[#B45309] border-[#D97706]/30'
  return 'bg-[#64748B]/10 text-[#64748B] border-[#64748B]/30'
}

function getProfileLabel(confidence) {
  if (confidence >= 0.7) return 'Full Profile'
  if (confidence >= 0.4) return 'Partial Profile'
  return 'Limited Data'
}

function formatStat(value, isPercent = false) {
  if (value === null || value === undefined || value === '') return '--'
  if (isPercent && typeof value === 'number') {
    // Reports store shooting percentages as 0-1 decimals; render as 40.2%.
    // Tolerate legacy cached reports that stored 40.2 directly.
    const pct = value <= 1 ? value * 100 : value
    return `${pct.toFixed(1)}%`
  }
  return String(value)
}

function confidenceMeterColors(confidence) {
  if (confidence >= 0.7) return { fill: '#16A34A', track: 'rgba(22, 163, 74, 0.15)' }
  if (confidence >= 0.4) return { fill: '#D97706', track: 'rgba(217, 119, 6, 0.15)' }
  return { fill: '#64748B', track: 'rgba(100, 116, 139, 0.15)' }
}

function formatDraftProjectionRound(round) {
  if (!round) return '--'
  if (round === 'Lottery') return 'Lottery Pick'
  if (round === 'Late First') return 'Late First Pick'
  if (round === 'Second Round') return 'Second Round Pick'
  return round
}

function sourceHost(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

const TOOL_LABELS = {
  web_search: 'Searching the web',
  get_player_stats: 'Checking Basketball Reference',
  get_college_stats: 'Pulling college stats',
  get_espn_college_stats: 'Checking ESPN college stats',
  get_wingspan: 'Looking up wingspan',
  get_euroleague_stats: 'Checking Euroleague stats',
  get_fiba_profile: 'Checking FIBA profile',
}

function stepLabelFromEvent(event) {
  if (event.type === 'tool') {
    const base = TOOL_LABELS[event.tool] || event.tool
    return event.query ? `${base}: “${event.query}”` : base
  }
  return event.label || 'Working…'
}

// ─── ProgressSteps ──────────────────────────────────────────────────────────

function ProgressSteps({ steps, elapsed, playerName }) {
  return (
    <section className="mb-6 rounded-xl border border-[#E2E8F0] bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm font-semibold text-[#0F172A]">Scouting {playerName}</p>
        <span className="text-xs tabular-nums text-[#64748B]">{elapsed}s</span>
      </div>
      <ul className="space-y-2.5">
        {steps.length === 0 && (
          <li className="flex items-center gap-3">
            <span className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-[#E2E8F0] border-t-[#2d8b8b]" />
            <span className="text-sm text-[#64748B]">Starting the scout agent…</span>
          </li>
        )}
        {steps.map((step) => (
          <li key={step.id} className="flex items-center gap-3">
            {step.status === 'done' ? (
              <svg className="h-4 w-4 shrink-0 text-[#16A34A]" viewBox="0 0 16 16" fill="none">
                <path d="M3 8.5L6.5 12L13 4.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            ) : (
              <span className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-[#E2E8F0] border-t-[#2d8b8b]" />
            )}
            <span className={`text-sm ${step.status === 'done' ? 'text-[#64748B]' : 'font-medium text-[#0F172A]'}`}>
              {step.label}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}

// ─── ReportCard ─────────────────────────────────────────────────────────────

function ReportCard({ report, onShare, copied, responseTime }) {
  const stats = [
    { label: 'Points', value: formatStat(report?.stats?.pts) },
    { label: 'Rebounds', value: formatStat(report?.stats?.reb) },
    { label: 'Assists', value: formatStat(report?.stats?.ast) },
    { label: 'Field goal %', value: formatStat(report?.stats?.fg_pct, true) },
    { label: 'Three point %', value: formatStat(report?.stats?.three_pct, true) },
    { label: 'Free throw %', value: formatStat(report?.stats?.ft_pct, true) },
  ]
  const physical = [
    { label: 'Height', value: report?.physical?.height ?? '--' },
    { label: 'Weight', value: report?.physical?.weight ?? '--' },
    { label: 'Wingspan', value: report?.physical?.wingspan ?? '--' },
  ]
  const confidence = typeof report?.confidence === 'number' ? report.confidence : 0
  const sources = Array.isArray(report?.sources) ? report.sources.slice(0, 5) : []

  return (
    <section className="rounded-xl border border-[#E2E8F0] bg-white p-6 shadow-sm">
      <div className="mb-5 border-b border-[#E2E8F0] pb-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h2 className="text-3xl font-bold tracking-tight text-[#0F172A]">{report.player_name ?? '--'}</h2>
          {onShare && (
            <div className="relative pt-1">
              <button
                type="button"
                onClick={onShare}
                className="rounded-md border border-[#E2E8F0] bg-white px-3 py-1 text-xs font-semibold text-[#64748B] transition hover:border-[#2d8b8b] hover:text-[#17595c]"
              >
                Share
              </button>
              {copied && (
                <span className="absolute left-1/2 top-full mt-2 -translate-x-1/2 whitespace-nowrap rounded-md border border-[#E2E8F0] bg-white px-2 py-1 text-[10px] font-semibold text-[#15803D] shadow-sm">
                  Copied!
                </span>
              )}
            </div>
          )}
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm font-medium text-[#1f6f6f]">
          <span>{report.position ?? '--'}</span>
          <span className="text-[#CBD5E1]">·</span>
          <span>{report.team ?? '--'}</span>
          <span className="text-[#CBD5E1]">·</span>
          <span>{report.age != null ? `${report.age} yrs` : '--'}</span>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className={`inline-flex rounded-full border px-3 py-1 text-xs font-semibold ${getConfidenceStyle(confidence)}`}>
            {getProfileLabel(confidence)}
          </span>
          <span className="text-xs text-[#64748B]">confidence {confidence.toFixed(2)}</span>
        </div>
        <div className="mt-2 max-w-[240px]">
          <div
            className="h-1.5 w-full overflow-hidden rounded-full"
            style={{ backgroundColor: confidenceMeterColors(confidence).track }}
            role="meter"
            aria-valuemin={0}
            aria-valuemax={1}
            aria-valuenow={confidence}
            aria-label="Report confidence"
          >
            <div
              className="h-full rounded-full"
              style={{
                width: `${Math.round(confidence * 100)}%`,
                backgroundColor: confidenceMeterColors(confidence).fill,
              }}
            />
          </div>
        </div>
        {report.confidence_notes ? (
          <p className="mt-2 text-xs leading-relaxed text-[#64748B]">{report.confidence_notes}</p>
        ) : null}
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {stats.map((stat) => (
          <div key={stat.label} className="rounded-lg border border-[#E2E8F0] bg-white p-3 shadow-sm">
            <p className="text-xs font-semibold text-[#64748B]">{stat.label}</p>
            <p className="mt-1 text-2xl font-bold text-[#0F172A]">{stat.value}</p>
          </div>
        ))}
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        {physical.map((item) => (
          <div key={item.label} className="rounded-lg border border-[#E2E8F0] bg-[#a8dadc]/25 p-3">
            <p className="text-xs font-semibold text-[#64748B]">{item.label}</p>
            <p className="mt-1 text-lg font-semibold text-[#0F172A]">{item.value}</p>
          </div>
        ))}
      </div>

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-[#E2E8F0] border-l-4 border-l-[#16A34A] bg-white p-4 shadow-sm">
          <h3 className="mb-3 text-sm font-bold text-[#15803D]">Strengths</h3>
          <ul className="space-y-2 text-sm leading-relaxed text-[#0F172A]">
            {(report.strengths ?? []).length > 0 ? (
              report.strengths.map((item, idx) => (
                <li key={idx} className="flex items-start gap-2">
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-[#16A34A]" />
                  <span>{item}</span>
                </li>
              ))
            ) : (
              <li className="text-[#64748B]">--</li>
            )}
          </ul>
        </div>

        <div className="rounded-lg border border-[#E2E8F0] border-l-4 border-l-[#DC2626] bg-white p-4 shadow-sm">
          <h3 className="mb-3 text-sm font-bold text-[#DC2626]">Weaknesses</h3>
          <ul className="space-y-2 text-sm leading-relaxed text-[#0F172A]">
            {(report.weaknesses ?? []).length > 0 ? (
              report.weaknesses.map((item, idx) => (
                <li key={idx} className="flex items-start gap-2">
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-[#DC2626]" />
                  <span>{item}</span>
                </li>
              ))
            ) : (
              <li className="text-[#64748B]">--</li>
            )}
          </ul>
        </div>
      </div>

      <div className="mt-6 rounded-lg border border-[#E2E8F0] border-l-4 border-l-[#2d8b8b] bg-white p-4 shadow-sm">
        <p className="text-xs font-bold uppercase tracking-wide text-[#1f6f6f]">NBA Comparison</p>
        <p className="mt-1 text-2xl font-bold text-[#0F172A]">{report.nba_comp?.name ?? '--'}</p>
        <p className="mt-2 text-sm leading-relaxed text-[#64748B]">{report.nba_comp?.reasoning || '--'}</p>
      </div>

      {report.draft_projection !== null && report.draft_projection !== undefined && (
        <div className="mt-4 rounded-lg border border-[#E2E8F0] border-l-4 border-l-[#1a2332] bg-white p-4 shadow-sm">
          <p className="text-xs font-bold uppercase tracking-wide text-[#1a2332]">Draft Projection</p>
          <p className="mt-1 text-2xl font-bold text-[#0F172A]">
            {formatDraftProjectionRound(report.draft_projection?.round)}
            {report.draft_projection?.year != null ? (
              <span className="font-semibold text-[#64748B]"> ({report.draft_projection.year})</span>
            ) : null}
          </p>
          <p className="mt-2 text-sm leading-relaxed text-[#64748B]">
            {report.draft_projection?.notes?.trim() ? report.draft_projection.notes : '--'}
          </p>
        </div>
      )}

      <footer className="mt-6 border-t border-[#E2E8F0] pt-4 text-xs text-[#64748B]">
        {sources.length > 0 && (
          <p className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="font-semibold">Sources:</span>
            {sources.map((src) => (
              <a
                key={src}
                href={src}
                target="_blank"
                rel="noreferrer"
                className="text-[#1f6f6f] hover:underline"
              >
                {sourceHost(src)}
              </a>
            ))}
          </p>
        )}
        <p>Response time: {responseTime ?? report.response_time_seconds ?? '--'}s</p>
      </footer>
    </section>
  )
}

// ─── HeadToHeadTable ─────────────────────────────────────────────────────────

function HeadToHeadTable({ r1, r2 }) {
  // highlight=true rows: winner blue, loser gray, null → both default
  const rows = [
    { label: 'PTS', v1: r1?.stats?.pts, v2: r2?.stats?.pts, fmt: (v) => formatStat(v), highlight: true },
    { label: 'REB', v1: r1?.stats?.reb, v2: r2?.stats?.reb, fmt: (v) => formatStat(v), highlight: true },
    { label: 'AST', v1: r1?.stats?.ast, v2: r2?.stats?.ast, fmt: (v) => formatStat(v), highlight: true },
    { label: 'FG%', v1: r1?.stats?.fg_pct, v2: r2?.stats?.fg_pct, fmt: (v) => formatStat(v, true), highlight: true },
    { label: '3PT%', v1: r1?.stats?.three_pct, v2: r2?.stats?.three_pct, fmt: (v) => formatStat(v, true), highlight: true },
    { label: 'FT%', v1: r1?.stats?.ft_pct, v2: r2?.stats?.ft_pct, fmt: (v) => formatStat(v, true), highlight: true },
    { label: 'Height', v1: r1?.physical?.height, v2: r2?.physical?.height, fmt: (v) => v ?? '--', highlight: false },
    { label: 'Weight', v1: r1?.physical?.weight, v2: r2?.physical?.weight, fmt: (v) => v ?? '--', highlight: false },
    { label: 'Wingspan', v1: r1?.physical?.wingspan, v2: r2?.physical?.wingspan, fmt: (v) => v ?? '--', highlight: false },
  ]

  return (
    <div className="mb-4 overflow-hidden rounded-xl border border-[#E2E8F0] bg-white shadow-sm">
      <div className="grid grid-cols-3 border-b border-[#E2E8F0] bg-[#a8dadc]/25 px-4 py-3 text-xs font-bold uppercase tracking-wide text-[#1a2332]">
        <span>{r1?.player_name ?? 'Player 1'}</span>
        <span className="text-center text-[#64748B]">Stat</span>
        <span className="text-right">{r2?.player_name ?? 'Player 2'}</span>
      </div>
      {rows.map(({ label, v1, v2, fmt, highlight }) => {
        const bothPresent = highlight && v1 != null && v2 != null
        const p1Win = bothPresent && v1 - v2 > 0
        const p2Win = bothPresent && v1 - v2 < 0

        const cls1 = p1Win ? 'text-[#1a2332]' : p2Win ? 'text-[#64748B]' : 'text-[#0F172A]'
        const cls2 = p2Win ? 'text-[#1a2332]' : p1Win ? 'text-[#64748B]' : 'text-[#0F172A]'

        return (
          <div key={label} className="grid grid-cols-3 border-b border-[#E2E8F0] px-4 py-3 last:border-b-0">
            <span className={`text-sm font-semibold tabular-nums ${cls1}`}>
              {p1Win && <span aria-label="higher value" className="mr-1 text-[10px]">▲</span>}
              {fmt(v1)}
            </span>
            <span className="text-center text-xs font-medium uppercase tracking-wide text-[#64748B]">{label}</span>
            <span className={`text-right text-sm font-semibold tabular-nums ${cls2}`}>
              {p2Win && <span aria-label="higher value" className="mr-1 text-[10px]">▲</span>}
              {fmt(v2)}
            </span>
          </div>
        )
      })}
    </div>
  )
}

// ─── App ─────────────────────────────────────────────────────────────────────

export default function App() {
  const [mode, setMode] = useState('scout')

  // Scout mode state
  const [playerName, setPlayerName] = useState('')
  const [teamOrSchool, setTeamOrSchool] = useState('')
  const [loading, setLoading] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [steps, setSteps] = useState([])
  const [report, setReport] = useState(null)
  const [error, setError] = useState(null)
  const [copied, setCopied] = useState(false)
  const didAutoRunDeepLink = useRef(false)
  const runRef = useRef(null)

  // Compare mode state
  const [p1Name, setP1Name] = useState('')
  const [p2Name, setP2Name] = useState('')
  const [compareLoading, setCompareLoading] = useState(false)
  const [comparison, setComparison] = useState(null)
  const [compareError, setCompareError] = useState(null)

  // Recent searches
  const [recentSearches, setRecentSearches] = useState([])

  function refreshRecent() {
    fetch(`${API_URL}/recent`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => (Array.isArray(d) ? setRecentSearches(d) : null))
      .catch(() => null)
  }

  function addStepFromEvent(event, runState) {
    if (runState.cancelled) return
    const label = stepLabelFromEvent(event)
    setSteps((prev) => [
      ...prev.map((s) => ({ ...s, status: 'done' })),
      { id: prev.length, label, status: 'active' },
    ])
  }

  // Primary path: POST /scout/stream (SSE). Returns the report, or null if the
  // endpoint doesn't exist yet (older deployed backend) so we can fall back.
  async function streamScout(combinedName, runState) {
    const resp = await fetch(`${API_URL}/scout/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ player_name: combinedName }),
    })
    if (resp.status === 404 || resp.status === 405) return null
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}))
      throw new Error(data?.detail || 'Failed to generate scouting report')
    }
    if (!resp.body) return null

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let result = null

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      if (runState.cancelled) {
        reader.cancel().catch(() => null)
        return result
      }
      buffer += decoder.decode(value, { stream: true })
      const chunks = buffer.split('\n\n')
      buffer = chunks.pop()
      for (const chunk of chunks) {
        const line = chunk.split('\n').find((l) => l.startsWith('data: '))
        if (!line) continue
        let event
        try {
          event = JSON.parse(line.slice(6))
        } catch {
          continue
        }
        if (event.type === 'report') {
          result = event.report
        } else if (event.type === 'error') {
          throw new Error(event.detail || 'Scouting failed')
        } else {
          addStepFromEvent(event, runState)
        }
      }
    }
    return result
  }

  // Fallback path: job-based POST /scout + poll GET /scout/{job_id}.
  async function pollScout(combinedName, runState, startTime) {
    const POLL_INTERVAL_MS = 2000
    const TIMEOUT_MS = 90000

    const response = await fetch(`${API_URL}/scout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ player_name: combinedName }),
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(data?.detail || 'Failed to generate scouting report')
    const jobId = data?.job_id
    if (!jobId) return data?.player_name ? data : null

    while (!runState.cancelled) {
      if (Date.now() - startTime > TIMEOUT_MS) {
        throw new Error('Scouting timed out after 90 seconds. Please try again.')
      }
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS))
      if (runState.cancelled) return null

      const pollResp = await fetch(`${API_URL}/scout/${jobId}`)
      const pollData = await pollResp.json().catch(() => ({}))
      if (!pollResp.ok) {
        if (pollResp.status === 404) throw new Error('Scouting job not found.')
        throw new Error(pollData?.detail || 'Failed to fetch scouting status')
      }
      if (pollData.status === 'complete') return pollData.report
      if (pollData.status === 'error') throw new Error(pollData.detail || 'Scouting failed')
      // status === 'processing' → keep polling
    }
    return null
  }

  async function generateReport(nextPlayerName, nextTeamOrSchool) {
    const trimmedPlayer = String(nextPlayerName ?? '').trim()
    const trimmedTeam = String(nextTeamOrSchool ?? '').trim()
    if (!trimmedPlayer) return
    const combinedPlayerName = trimmedTeam ? `${trimmedPlayer} ${trimmedTeam}` : trimmedPlayer

    // Cancel any run still in flight from a previous search.
    if (runRef.current) runRef.current.cancelled = true
    const runState = { cancelled: false }
    runRef.current = runState

    setLoading(true)
    setError(null)
    setReport(null)
    setSteps([])
    setElapsed(0)

    const startTime = Date.now()
    const elapsedTimer = setInterval(() => {
      if (runState.cancelled) return
      setElapsed(Math.floor((Date.now() - startTime) / 1000))
    }, 1000)

    try {
      let result = await streamScout(combinedPlayerName, runState)
      if (result === null && !runState.cancelled) {
        addStepFromEvent({ type: 'phase', label: `Researching ${trimmedPlayer}` }, runState)
        result = await pollScout(combinedPlayerName, runState, startTime)
      }
      if (runState.cancelled) return
      if (!result) throw new Error('No report returned from server')
      setSteps((prev) => prev.map((s) => ({ ...s, status: 'done' })))
      setReport(result)
      refreshRecent()
    } catch (err) {
      if (!runState.cancelled) {
        setError(err instanceof Error ? err.message : 'Unexpected error')
      }
    } finally {
      clearInterval(elapsedTimer)
      if (!runState.cancelled) setLoading(false)
    }
  }

  async function handleSubmit(event) {
    event.preventDefault()
    await generateReport(playerName, teamOrSchool)
  }

  async function handleShare() {
    if (!report?.player_name) return
    try {
      const url = new URL(window.location.href)
      url.searchParams.set('player', report.player_name)
      await navigator.clipboard.writeText(url.toString())
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  async function handleCompare(event) {
    event.preventDefault()
    const t1 = p1Name.trim()
    const t2 = p2Name.trim()
    if (!t1 || !t2) return
    setCompareLoading(true)
    setCompareError(null)
    setComparison(null)
    try {
      const response = await fetch(`${API_URL}/compare`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ player_one: t1, player_two: t2 }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data?.detail || 'Failed to compare players')
      setComparison(data)
    } catch (err) {
      setCompareError(err instanceof Error ? err.message : 'Unexpected error')
    } finally {
      setCompareLoading(false)
    }
  }

  useEffect(() => {
    if (didAutoRunDeepLink.current) return
    if (typeof window !== 'undefined' && window.__nbaScoutDeepLinkAutoRun) return
    didAutoRunDeepLink.current = true
    if (typeof window !== 'undefined') window.__nbaScoutDeepLinkAutoRun = true

    const params = new URLSearchParams(window.location.search)
    const sharedPlayer = params.get('player')
    if (!sharedPlayer || !sharedPlayer.trim()) return

    const decodedPlayer = sharedPlayer.trim()
    setPlayerName(decodedPlayer)
    setTeamOrSchool('')
    void generateReport(decodedPlayer, '')
  }, [])

  useEffect(() => {
    refreshRecent()
  }, [])

  const inputCls =
    'h-12 w-full rounded-lg border border-[#E2E8F0] bg-white px-4 text-[#0F172A] ' +
    'placeholder:text-[#94A3B8] shadow-sm outline-none transition focus:border-[#2d8b8b] focus:ring-2 focus:ring-[#2d8b8b]/20'

  const primaryBtnCls =
    'h-12 rounded-lg bg-[#1a2332] px-6 font-semibold text-white shadow-sm transition ' +
    'hover:bg-[#17595c] disabled:cursor-not-allowed disabled:opacity-50'

  return (
    <div className="flex min-h-screen flex-col bg-[#f1faee] font-[system-ui] text-[#0F172A]">

      {/* header */}
      <header className="border-b border-[#E2E8F0] bg-white">
        <div className="mx-auto flex w-full max-w-[960px] items-center justify-between px-4 py-4">
          <div className="flex items-center gap-2">
            <span className="text-xl font-bold tracking-tight text-[#1a2332]">NBAScout</span>
            <span className="rounded bg-[#17595c] px-1.5 py-0.5 text-[10px] font-bold uppercase leading-none text-white">
              AI
            </span>
          </div>
          <p className="hidden text-xs text-[#64748B] sm:block">
            Scouting reports for college &amp; international prospects
          </p>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[960px] flex-1 px-4 py-8">

        {/* mode tabs */}
        <div className="mb-6 border-b border-[#E2E8F0]">
          <nav className="-mb-px flex gap-6">
            {[
              { key: 'scout', label: 'Scout Player' },
              { key: 'compare', label: 'Compare Players' },
            ].map((tab) => (
              <button
                key={tab.key}
                type="button"
                onClick={() => setMode(tab.key)}
                className={`border-b-2 pb-3 text-sm transition ${
                  mode === tab.key
                    ? 'border-[#2d8b8b] font-semibold text-[#1a2332]'
                    : 'border-transparent font-medium text-[#64748B] hover:text-[#0F172A]'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        </div>

        {/* ── Scout mode ── */}
        {mode === 'scout' && (
          <>
            <section className="mb-6 rounded-xl border border-[#E2E8F0] bg-white p-5 shadow-sm">
              <form onSubmit={handleSubmit} className="flex flex-col gap-3">
                <input
                  type="text"
                  value={playerName}
                  onChange={(e) => setPlayerName(e.target.value)}
                  placeholder="Player name"
                  className={inputCls}
                  required
                />
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                  <input
                    type="text"
                    value={teamOrSchool}
                    onChange={(e) => setTeamOrSchool(e.target.value)}
                    placeholder="Team or school (optional)"
                    className="h-10 w-full rounded-lg border border-[#E2E8F0] bg-white px-3 text-sm text-[#0F172A] placeholder:text-[#94A3B8] shadow-sm outline-none transition focus:border-[#2d8b8b] focus:ring-2 focus:ring-[#2d8b8b]/20 sm:max-w-[320px]"
                  />
                  <button type="submit" disabled={loading || !playerName.trim()} className={primaryBtnCls}>
                    Generate Report
                  </button>
                </div>
              </form>
            </section>

            {!report && !loading && recentSearches.length > 0 && (
              <div className="mb-6">
                <p className="mb-2 text-xs font-bold uppercase tracking-wide text-[#475569]">
                  Recent Searches
                </p>
                <div className="flex flex-wrap gap-2">
                  {recentSearches.slice(0, 8).map((entry) => (
                    <button
                      key={entry.player_name}
                      type="button"
                      onClick={() => {
                        setPlayerName(entry.player_name)
                        setTeamOrSchool('')
                        void generateReport(entry.player_name, '')
                      }}
                      className="flex items-center gap-1.5 rounded-full border border-[#E2E8F0] bg-white px-3 py-1.5 text-sm shadow-sm transition hover:border-[#2d8b8b]/60 hover:bg-[#f1faee]"
                    >
                      <span className="font-medium text-[#0F172A]">{entry.player_name}</span>
                      {entry.position && (
                        <span className="text-xs font-semibold text-[#1f6f6f]">{entry.position}</span>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {loading && <ProgressSteps steps={steps} elapsed={elapsed} playerName={playerName} />}

            {error && (
              <section className="mb-6 rounded-lg border border-[#DC2626]/30 bg-[#DC2626]/5 p-4 text-sm font-medium text-[#B91C1C]">
                {error}
              </section>
            )}

            {report && !loading && (
              <ReportCard report={report} onShare={handleShare} copied={copied} />
            )}
          </>
        )}

        {/* ── Compare mode ── */}
        {mode === 'compare' && (
          <>
            <section className="mb-6 rounded-xl border border-[#E2E8F0] bg-white p-5 shadow-sm">
              <form onSubmit={handleCompare} className="flex flex-col gap-3">
                <div className="grid gap-3 sm:grid-cols-2">
                  <input
                    type="text"
                    value={p1Name}
                    onChange={(e) => setP1Name(e.target.value)}
                    placeholder="Player 1 name"
                    className={inputCls}
                    required
                  />
                  <input
                    type="text"
                    value={p2Name}
                    onChange={(e) => setP2Name(e.target.value)}
                    placeholder="Player 2 name"
                    className={inputCls}
                    required
                  />
                </div>
                <button
                  type="submit"
                  disabled={compareLoading || !p1Name.trim() || !p2Name.trim()}
                  className={`${primaryBtnCls} sm:self-start`}
                >
                  Compare
                </button>
              </form>
            </section>

            {compareLoading && (
              <section className="mb-6 rounded-xl border border-[#E2E8F0] bg-white p-5 shadow-sm">
                <div className="flex items-center gap-3">
                  <span className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-[#E2E8F0] border-t-[#2d8b8b]" />
                  <p className="text-sm text-[#64748B]">
                    Comparing <span className="font-semibold text-[#0F172A]">{p1Name}</span> vs{' '}
                    <span className="font-semibold text-[#0F172A]">{p2Name}</span>… usually under 30 seconds
                  </p>
                </div>
              </section>
            )}

            {compareError && (
              <section className="mb-6 rounded-lg border border-[#DC2626]/30 bg-[#DC2626]/5 p-4 text-sm font-medium text-[#B91C1C]">
                {compareError}
              </section>
            )}

            {comparison && !compareLoading && (
              <>
                <HeadToHeadTable r1={comparison.player_one} r2={comparison.player_two} />
                <p className="mb-6 text-center text-xs text-[#475569]">
                  Comparison generated in {comparison.response_time_seconds ?? '--'}s
                </p>
                <div className="grid gap-6 lg:grid-cols-2">
                  <ReportCard report={comparison.player_one} />
                  <ReportCard report={comparison.player_two} />
                </div>
              </>
            )}
          </>
        )}

      </main>

      {/* footer */}
      <footer className="border-t border-[#E2E8F0] bg-white py-6 text-center text-xs text-[#64748B]">
        nbascout.app · Free AI scouting for college and international prospects
      </footer>
    </div>
  )
}
