import { useEffect, useRef, useState } from 'react'
import './App.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// ─── palette: Front Office ──────────────────────────────────────────────────
// paper #FCFCFA · ink #14181d · hairline #DBDDD6 · muted #7a828c
// teal ink #1f6f6f (text) · teal #2d8b8b (graphics)
// status text steps: #15803D · #B45309 · #B91C1C

// ─── helpers ────────────────────────────────────────────────────────────────

function getProfileLabel(confidence) {
  if (confidence >= 0.7) return 'FULL PROFILE'
  if (confidence >= 0.4) return 'PARTIAL PROFILE'
  return 'LIMITED DATA'
}

function confidenceMeterColors(confidence) {
  if (confidence >= 0.7) return { fill: '#15803D', track: 'rgba(21, 128, 61, 0.14)' }
  if (confidence >= 0.4) return { fill: '#B45309', track: 'rgba(180, 83, 9, 0.14)' }
  return { fill: '#7a828c', track: 'rgba(122, 130, 140, 0.16)' }
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

function formatDraftProjectionRound(round) {
  if (!round) return '--'
  if (round === 'Lottery') return 'Lottery Pick'
  if (round === 'Late First') return 'Late First Pick'
  if (round === 'Second Round') return 'Second Round Pick'
  return round
}

function formatFileDate(iso) {
  if (!iso) return '--'
  try {
    const d = new Date(iso)
    return d.toISOString().slice(0, 10)
  } catch {
    return '--'
  }
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

// ─── shared editorial atoms ─────────────────────────────────────────────────

function MicroLabel({ children, className = '' }) {
  return (
    <span className={`font-mono text-[11px] font-medium uppercase tracking-[0.1em] ${className}`}>
      {children}
    </span>
  )
}

// ─── ProgressSteps ──────────────────────────────────────────────────────────

function ProgressSteps({ steps, elapsed, playerName }) {
  return (
    <section className="animate-reveal mb-10">
      <div className="flex items-baseline justify-between border-t-2 border-[#14181d] pt-3">
        <MicroLabel className="text-[#14181d]">Scouting {playerName}</MicroLabel>
        <span className="font-mono text-[11px] tabular-nums text-[#7a828c]">{elapsed}s</span>
      </div>
      <ul className="mt-3">
        {steps.length === 0 && (
          <li className="flex items-center gap-3 py-2">
            <span className="font-mono text-xs text-[#1f6f6f]">▸</span>
            <span className="font-mono text-xs text-[#7a828c]">Starting the scout agent…</span>
          </li>
        )}
        {steps.map((step) => (
          <li
            key={step.id}
            className="animate-reveal flex items-center gap-3 border-t border-[#DBDDD6] py-2 first:border-t-0"
          >
            {step.status === 'done' ? (
              <span className="font-mono text-xs text-[#15803D]">✓</span>
            ) : (
              <span className="animate-pulse font-mono text-xs text-[#1f6f6f]">▸</span>
            )}
            <span
              className={`font-mono text-xs ${
                step.status === 'done' ? 'text-[#7a828c]' : 'text-[#14181d]'
              }`}
            >
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
    { label: 'Field goal', value: formatStat(report?.stats?.fg_pct, true) },
    { label: 'Three point', value: formatStat(report?.stats?.three_pct, true) },
    { label: 'Free throw', value: formatStat(report?.stats?.ft_pct, true) },
  ]
  const physical = [
    { label: 'Height', value: report?.physical?.height ?? '--' },
    { label: 'Weight', value: report?.physical?.weight ?? '--' },
    { label: 'Wingspan', value: report?.physical?.wingspan ?? '--' },
  ]
  const advanced = report?.advanced || {}
  const advancedRows = [
    {
      key: 'ts_pct',
      label: 'TS% · True shooting',
      tip: 'True Shooting: scoring efficiency that accounts for threes and free throws',
      value: formatStat(advanced.ts_pct, true),
      present: advanced.ts_pct != null,
    },
    {
      key: 'usg_pct',
      label: 'USG% · Usage rate',
      tip: 'Usage Rate: share of team plays used while on the floor',
      value: formatStat(advanced.usg_pct, true),
      present: advanced.usg_pct != null,
    },
    {
      key: 'bpm',
      label: 'BPM · Box plus/minus',
      tip: 'Box Plus/Minus: estimated impact per 100 possessions versus an average player',
      value:
        typeof advanced.bpm === 'number'
          ? `${advanced.bpm > 0 ? '+' : ''}${advanced.bpm.toFixed(1)}`
          : '--',
      present: advanced.bpm != null,
    },
    {
      key: 'per',
      label: 'PER · Efficiency rating',
      tip: 'Player Efficiency Rating: per-minute production, league average is 15',
      value: typeof advanced.per === 'number' ? advanced.per.toFixed(1) : '--',
      present: advanced.per != null,
    },
  ].filter((row) => row.present)
  const confidence = typeof report?.confidence === 'number' ? report.confidence : 0
  const meter = confidenceMeterColors(confidence)
  const sources = Array.isArray(report?.sources) ? report.sources.slice(0, 5) : []
  const comp = report?.nba_comp
  const proj = report?.draft_projection

  return (
    <article className="animate-reveal">
      <div className="flex items-baseline justify-between">
        <MicroLabel className="text-[#7a828c]">
          File {formatFileDate(report?.generated_at)}
        </MicroLabel>
        {onShare && (
          <span className="relative">
            <button
              type="button"
              onClick={onShare}
              className="font-mono text-[11px] font-medium uppercase tracking-[0.1em] text-[#7a828c] underline decoration-[#DBDDD6] underline-offset-4 transition-colors hover:text-[#1f6f6f] hover:decoration-[#2d8b8b]"
            >
              Share
            </button>
            {copied && (
              <span className="absolute -bottom-6 right-0 whitespace-nowrap font-mono text-[10px] text-[#15803D]">
                Link copied
              </span>
            )}
          </span>
        )}
      </div>

      <h1 className="mt-4 font-display text-6xl leading-[1.02] tracking-tight text-[#14181d] sm:text-7xl">
        {report.player_name ?? '--'}
      </h1>
      <p className="mt-2 font-sans text-sm font-medium text-[#1f6f6f]">
        {report.position ?? '--'} · {report.team ?? '--'} ·{' '}
        {report.age != null ? `${report.age} yrs` : '--'}
        {report.season ? (
          <span className="text-[#7a828c]"> · {report.season} season</span>
        ) : null}
      </p>

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <span
          className="h-[3px] w-44 overflow-hidden rounded-full"
          style={{ backgroundColor: meter.track }}
          role="meter"
          aria-valuemin={0}
          aria-valuemax={1}
          aria-valuenow={confidence}
          aria-label="Report confidence"
        >
          <span
            className="block h-full rounded-full"
            style={{ width: `${Math.round(confidence * 100)}%`, backgroundColor: meter.fill }}
          />
        </span>
        <MicroLabel className="text-[#7a828c]">
          Confidence {confidence.toFixed(2)} · {getProfileLabel(confidence)}
        </MicroLabel>
      </div>
      {report.confidence_notes ? (
        <p className="mt-2 max-w-[52ch] font-sans text-xs leading-relaxed text-[#7a828c]">
          {report.confidence_notes}
        </p>
      ) : null}

      <div className="animate-reveal mt-8 grid gap-x-12 sm:grid-cols-2" style={{ animationDelay: '200ms' }}>
        {stats.map((stat) => (
          <div
            key={stat.label}
            className="flex items-baseline justify-between border-t border-[#DBDDD6] py-3"
          >
            <MicroLabel className="text-[#7a828c]">{stat.label}</MicroLabel>
            <span className="font-mono text-2xl font-semibold tabular-nums text-[#14181d]">
              {stat.value}
            </span>
          </div>
        ))}
      </div>

      <div className="animate-reveal grid gap-x-12 sm:grid-cols-3" style={{ animationDelay: '200ms' }}>
        {physical.map((item) => (
          <div
            key={item.label}
            className="flex items-baseline justify-between border-t border-[#DBDDD6] py-3"
          >
            <MicroLabel className="text-[#7a828c]">{item.label}</MicroLabel>
            <span className="font-mono text-lg font-medium text-[#14181d]">{item.value}</span>
          </div>
        ))}
      </div>

      {advancedRows.length > 0 && (
        <section className="animate-reveal mt-8" style={{ animationDelay: '200ms' }}>
          <div className="border-t-2 border-[#14181d] pt-3">
            <MicroLabel className="text-[#7a828c]">Advanced metrics</MicroLabel>
          </div>
          <div className="grid gap-x-12 sm:grid-cols-2">
            {advancedRows.map((row) => (
              <div
                key={row.key}
                className="flex items-baseline justify-between border-t border-[#DBDDD6] py-3 first:border-t-0 sm:[&:nth-child(2)]:border-t-0"
                title={row.tip}
              >
                <MicroLabel className="cursor-help text-[#7a828c]">{row.label}</MicroLabel>
                <span className="font-mono text-2xl font-semibold tabular-nums text-[#14181d]">
                  {row.value}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="animate-reveal mt-10 grid gap-x-12 gap-y-8 md:grid-cols-2" style={{ animationDelay: '400ms' }}>
        <section>
          <div className="border-t-2 border-[#14181d] pt-3">
            <MicroLabel className="text-[#15803D]">Strengths</MicroLabel>
          </div>
          <ul className="mt-2">
            {(report.strengths ?? []).length > 0 ? (
              report.strengths.map((item, idx) => (
                <li
                  key={idx}
                  className="flex gap-3 border-t border-[#DBDDD6] py-2.5 first:border-t-0"
                >
                  <span className="font-mono text-sm text-[#15803D]">+</span>
                  <span className="font-sans text-sm leading-relaxed text-[#14181d]">{item}</span>
                </li>
              ))
            ) : (
              <li className="py-2.5 font-sans text-sm text-[#7a828c]">--</li>
            )}
          </ul>
        </section>

        <section>
          <div className="border-t-2 border-[#14181d] pt-3">
            <MicroLabel className="text-[#B91C1C]">Weaknesses</MicroLabel>
          </div>
          <ul className="mt-2">
            {(report.weaknesses ?? []).length > 0 ? (
              report.weaknesses.map((item, idx) => (
                <li
                  key={idx}
                  className="flex gap-3 border-t border-[#DBDDD6] py-2.5 first:border-t-0"
                >
                  <span className="font-mono text-sm text-[#B91C1C]">−</span>
                  <span className="font-sans text-sm leading-relaxed text-[#14181d]">{item}</span>
                </li>
              ))
            ) : (
              <li className="py-2.5 font-sans text-sm text-[#7a828c]">--</li>
            )}
          </ul>
        </section>
      </div>

      <section className="animate-reveal mt-10 border-t-2 border-[#14181d] pt-4" style={{ animationDelay: '600ms' }}>
        <MicroLabel className="text-[#1f6f6f]">NBA Comparison</MicroLabel>
        <p className="mt-2 font-display text-4xl text-[#14181d]">{comp?.name ?? '--'}</p>
        {comp?.reasoning ? (
          <p className="mt-2 max-w-[58ch] font-display text-xl italic leading-snug text-[#3a4148]">
            {comp.reasoning}
          </p>
        ) : null}
      </section>

      {proj != null && (
        <section className="animate-reveal mt-8 border-t border-[#DBDDD6] pt-4" style={{ animationDelay: '600ms' }}>
          <MicroLabel className="text-[#7a828c]">Draft Projection</MicroLabel>
          <p className="mt-1 font-sans text-lg font-semibold text-[#14181d]">
            {formatDraftProjectionRound(proj?.round)}
            {proj?.year != null ? <span className="text-[#7a828c]"> ({proj.year})</span> : null}
          </p>
          {proj?.notes?.trim() ? (
            <p className="mt-1 max-w-[58ch] font-sans text-sm leading-relaxed text-[#7a828c]">
              {proj.notes}
            </p>
          ) : null}
        </section>
      )}

      <footer className="animate-reveal mt-10 border-t border-[#DBDDD6] pt-3 font-mono text-[11px] text-[#7a828c]" style={{ animationDelay: '600ms' }}>
        {sources.length > 0 && (
          <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="uppercase tracking-[0.1em]">Sources</span>
            {sources.map((src) => (
              <a
                key={src}
                href={src}
                target="_blank"
                rel="noreferrer"
                className="underline decoration-[#DBDDD6] underline-offset-4 transition-colors hover:text-[#1f6f6f] hover:decoration-[#2d8b8b]"
              >
                {sourceHost(src)}
              </a>
            ))}
          </p>
        )}
        <p className="mt-2">
          Generated in {responseTime ?? report.response_time_seconds ?? '--'}s
        </p>
      </footer>
    </article>
  )
}

// ─── HeadToHeadTable ─────────────────────────────────────────────────────────

function HeadToHeadTable({ r1, r2 }) {
  const rows = [
    { label: 'PTS', v1: r1?.stats?.pts, v2: r2?.stats?.pts, fmt: (v) => formatStat(v), highlight: true },
    { label: 'REB', v1: r1?.stats?.reb, v2: r2?.stats?.reb, fmt: (v) => formatStat(v), highlight: true },
    { label: 'AST', v1: r1?.stats?.ast, v2: r2?.stats?.ast, fmt: (v) => formatStat(v), highlight: true },
    { label: 'FG', v1: r1?.stats?.fg_pct, v2: r2?.stats?.fg_pct, fmt: (v) => formatStat(v, true), highlight: true },
    { label: '3PT', v1: r1?.stats?.three_pct, v2: r2?.stats?.three_pct, fmt: (v) => formatStat(v, true), highlight: true },
    { label: 'FT', v1: r1?.stats?.ft_pct, v2: r2?.stats?.ft_pct, fmt: (v) => formatStat(v, true), highlight: true },
    { label: 'HT', v1: r1?.physical?.height, v2: r2?.physical?.height, fmt: (v) => v ?? '--', highlight: false },
    { label: 'WT', v1: r1?.physical?.weight, v2: r2?.physical?.weight, fmt: (v) => v ?? '--', highlight: false },
    { label: 'WING', v1: r1?.physical?.wingspan, v2: r2?.physical?.wingspan, fmt: (v) => v ?? '--', highlight: false },
  ]

  return (
    <div className="animate-reveal mb-10">
      <div className="grid grid-cols-3 border-t-2 border-[#14181d] pt-3">
        <span className="font-sans text-sm font-bold text-[#14181d]">
          {r1?.player_name ?? 'Player 1'}
        </span>
        <span className="text-center font-mono text-[11px] uppercase tracking-[0.1em] text-[#7a828c]">
          Head to head
        </span>
        <span className="text-right font-sans text-sm font-bold text-[#14181d]">
          {r2?.player_name ?? 'Player 2'}
        </span>
      </div>
      <div className="mt-2">
        {rows.map(({ label, v1, v2, fmt, highlight }) => {
          const bothPresent = highlight && v1 != null && v2 != null
          const p1Win = bothPresent && v1 - v2 > 0
          const p2Win = bothPresent && v1 - v2 < 0
          const cls1 = p1Win ? 'font-semibold text-[#14181d]' : p2Win ? 'text-[#7a828c]' : 'text-[#14181d]'
          const cls2 = p2Win ? 'font-semibold text-[#14181d]' : p1Win ? 'text-[#7a828c]' : 'text-[#14181d]'
          return (
            <div key={label} className="grid grid-cols-3 border-t border-[#DBDDD6] py-2.5">
              <span className={`font-mono text-sm tabular-nums ${cls1}`}>
                {p1Win && <span aria-label="higher value" className="mr-1.5 text-[10px]">▲</span>}
                {fmt(v1)}
              </span>
              <span className="text-center font-mono text-[11px] uppercase tracking-[0.1em] text-[#7a828c]">
                {label}
              </span>
              <span className={`text-right font-mono text-sm tabular-nums ${cls2}`}>
                {p2Win && <span aria-label="higher value" className="mr-1.5 text-[10px]">▲</span>}
                {fmt(v2)}
              </span>
            </div>
          )
        })}
      </div>
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
  // Team goes in its own field so the backend can validate tool-returned teams
  // against it instead of substring-matching a concatenated search string.
  async function streamScout(name, teamContext, runState) {
    const resp = await fetch(`${API_URL}/scout/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ player_name: name, team_context: teamContext || null }),
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
  async function pollScout(name, teamContext, runState, startTime) {
    const POLL_INTERVAL_MS = 2000
    const TIMEOUT_MS = 90000

    const response = await fetch(`${API_URL}/scout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ player_name: name, team_context: teamContext || null }),
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
      let result = await streamScout(trimmedPlayer, trimmedTeam, runState)
      if (result === null && !runState.cancelled) {
        addStepFromEvent({ type: 'phase', label: `Researching ${trimmedPlayer}` }, runState)
        result = await pollScout(trimmedPlayer, trimmedTeam, runState, startTime)
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

  return (
    <div className="min-h-screen bg-[#FCFCFA] font-sans text-[#14181d]">

      {/* masthead */}
      <header className="border-b-2 border-[#14181d]">
        <div className="mx-auto flex w-full max-w-[760px] items-baseline justify-between px-5 py-4">
          <div className="flex items-baseline gap-2.5">
            <span className="text-xl font-bold tracking-tight">NBAScout</span>
            <MicroLabel className="text-[#1f6f6f]">AI Scouting</MicroLabel>
          </div>
          <MicroLabel className="hidden text-[#7a828c] sm:block">
            College · International · Draft
          </MicroLabel>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[760px] px-5 pb-24 pt-8">

        {/* mode tabs */}
        <nav className="flex gap-8 border-b border-[#DBDDD6]">
          {[
            { key: 'scout', label: 'Scout Player' },
            { key: 'compare', label: 'Compare' },
          ].map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => setMode(tab.key)}
              className={`-mb-px border-b-2 pb-3 font-mono text-xs uppercase tracking-[0.12em] transition-colors ${
                mode === tab.key
                  ? 'border-[#14181d] font-semibold text-[#14181d]'
                  : 'border-transparent font-medium text-[#7a828c] hover:text-[#14181d]'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>

        {/* ── Scout mode ── */}
        {mode === 'scout' && (
          <>
            <form onSubmit={handleSubmit} className="mt-10">
              <input
                type="text"
                value={playerName}
                onChange={(e) => setPlayerName(e.target.value)}
                placeholder="Player name"
                className="w-full border-b border-[#DBDDD6] bg-transparent pb-3 font-display text-4xl text-[#14181d] outline-none transition-colors placeholder:text-[#c3c6bd] focus:border-[#14181d] sm:text-5xl"
                required
              />
              <div className="mt-4 flex flex-col gap-4 sm:flex-row sm:items-end">
                <input
                  type="text"
                  value={teamOrSchool}
                  onChange={(e) => setTeamOrSchool(e.target.value)}
                  placeholder="Team or school (optional)"
                  className="w-full border-b border-[#DBDDD6] bg-transparent pb-2 font-sans text-sm text-[#14181d] outline-none transition-colors placeholder:text-[#a9ada3] focus:border-[#14181d] sm:max-w-[300px]"
                />
                <button
                  type="submit"
                  disabled={loading || !playerName.trim()}
                  className="h-11 shrink-0 rounded-[3px] bg-[#14181d] px-7 font-sans text-sm font-semibold text-[#FCFCFA] transition-colors hover:bg-[#1f6f6f] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Generate Report
                </button>
              </div>
            </form>

            {!report && !loading && recentSearches.length > 0 && (
              <div className="mt-10">
                <MicroLabel className="text-[#7a828c]">Recent files · from all visitors</MicroLabel>
                <p className="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-1.5 font-sans text-sm">
                  {recentSearches.slice(0, 8).map((entry, idx) => (
                    <span key={entry.player_name} className="flex items-baseline gap-x-2">
                      {idx > 0 && <span className="text-[#c3c6bd]">/</span>}
                      <button
                        type="button"
                        onClick={() => {
                          setPlayerName(entry.player_name)
                          setTeamOrSchool('')
                          void generateReport(entry.player_name, '')
                        }}
                        className="font-medium text-[#1f6f6f] underline decoration-[#2d8b8b]/40 underline-offset-4 transition-colors hover:decoration-[#1f6f6f]"
                      >
                        {entry.player_name}
                      </button>
                      {entry.position && (
                        <span className="font-mono text-[10px] uppercase text-[#7a828c]">
                          {entry.position}
                        </span>
                      )}
                    </span>
                  ))}
                </p>
              </div>
            )}

            <div className="mt-10">
              {loading && <ProgressSteps steps={steps} elapsed={elapsed} playerName={playerName} />}

              {error && (
                <section className="animate-reveal mb-10 border-t-2 border-[#B91C1C] pt-3">
                  <MicroLabel className="text-[#B91C1C]">Error</MicroLabel>
                  <p className="mt-1 font-sans text-sm text-[#B91C1C]">{error}</p>
                </section>
              )}

              {report && !loading && (
                <ReportCard report={report} onShare={handleShare} copied={copied} />
              )}
            </div>
          </>
        )}

        {/* ── Compare mode ── */}
        {mode === 'compare' && (
          <>
            <form onSubmit={handleCompare} className="mt-10">
              <div className="grid gap-6 sm:grid-cols-2">
                <input
                  type="text"
                  value={p1Name}
                  onChange={(e) => setP1Name(e.target.value)}
                  placeholder="Player one"
                  className="w-full border-b border-[#DBDDD6] bg-transparent pb-3 font-display text-3xl text-[#14181d] outline-none transition-colors placeholder:text-[#c3c6bd] focus:border-[#14181d]"
                  required
                />
                <input
                  type="text"
                  value={p2Name}
                  onChange={(e) => setP2Name(e.target.value)}
                  placeholder="Player two"
                  className="w-full border-b border-[#DBDDD6] bg-transparent pb-3 font-display text-3xl text-[#14181d] outline-none transition-colors placeholder:text-[#c3c6bd] focus:border-[#14181d]"
                  required
                />
              </div>
              <button
                type="submit"
                disabled={compareLoading || !p1Name.trim() || !p2Name.trim()}
                className="mt-5 h-11 rounded-[3px] bg-[#14181d] px-7 font-sans text-sm font-semibold text-[#FCFCFA] transition-colors hover:bg-[#1f6f6f] disabled:cursor-not-allowed disabled:opacity-40"
              >
                Compare
              </button>
            </form>

            <div className="mt-10">
              {compareLoading && (
                <section className="animate-reveal mb-10 border-t-2 border-[#14181d] pt-3">
                  <div className="flex items-baseline justify-between">
                    <MicroLabel className="text-[#14181d]">
                      Comparing {p1Name} and {p2Name}
                    </MicroLabel>
                    <span className="animate-pulse font-mono text-xs text-[#1f6f6f]">▸</span>
                  </div>
                  <p className="mt-1 font-mono text-xs text-[#7a828c]">
                    Two full scouting files, usually under 30 seconds
                  </p>
                </section>
              )}

              {compareError && (
                <section className="animate-reveal mb-10 border-t-2 border-[#B91C1C] pt-3">
                  <MicroLabel className="text-[#B91C1C]">Error</MicroLabel>
                  <p className="mt-1 font-sans text-sm text-[#B91C1C]">{compareError}</p>
                </section>
              )}

              {comparison && !compareLoading && (
                <>
                  <HeadToHeadTable r1={comparison.player_one} r2={comparison.player_two} />
                  <div className="grid gap-14 lg:grid-cols-2">
                    <ReportCard report={comparison.player_one} />
                    <ReportCard report={comparison.player_two} />
                  </div>
                </>
              )}
            </div>
          </>
        )}

      </main>
    </div>
  )
}
