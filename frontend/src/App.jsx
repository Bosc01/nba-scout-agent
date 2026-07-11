import { useEffect, useRef, useState } from 'react'
import './App.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Rotating placeholder examples for the scout search input.
const PLACEHOLDER_EXAMPLES = ['Cooper Flagg', 'Zaccharie Risacher', 'Camden Heide']

// Multi-step loading indicator — step is chosen by elapsed seconds (`until` is exclusive upper bound).
const LOADING_STEPS = [
  { label: 'Searching Basketball Reference…', until: 5 },
  { label: 'Checking college stats…', until: 10 },
  { label: 'Running web searches…', until: 20 },
  { label: 'Synthesizing report…', until: Infinity },
]

// Shared surface styles — deep navy card with subtle depth, and a lighter inner tile.
const CARD = 'rounded-lg border border-[#233251] bg-[#111A2E] shadow-[0_16px_50px_-28px_rgba(0,0,0,0.9)]'
const TILE = 'rounded-lg border border-[#233251] bg-[#17233E]'

// ─── helpers ────────────────────────────────────────────────────────────────

// Profile tier drives the badge style and the report card's colored top border.
function getProfileTheme(confidence) {
  if (confidence >= 0.7) {
    return { label: 'Full Profile', badge: 'border-[#34D399]/30 bg-[#34D399]/10 text-[#34D399]', border: '#34D399' }
  }
  if (confidence >= 0.4) {
    return { label: 'Partial Profile', badge: 'border-[#FBBF24]/30 bg-[#FBBF24]/10 text-[#FBBF24]', border: '#FBBF24' }
  }
  return { label: 'Limited Data', badge: 'border-[#94A3B8]/30 bg-[#94A3B8]/10 text-[#94A3B8]', border: '#94A3B8' }
}

function formatStat(value, isPercent = false) {
  if (value === null || value === undefined || value === '') return '--'
  if (isPercent && typeof value === 'number') return value.toFixed(3)
  return String(value)
}

function formatDraftProjectionRound(round) {
  if (!round) return '--'
  if (round === 'Lottery') return 'Lottery Pick'
  if (round === 'Late First') return 'Late First Pick'
  if (round === 'Second Round') return 'Second Round Pick'
  if (round === 'Undrafted') return 'Undrafted'
  if (round === 'Too Early To Project') return 'Too Early To Project'
  return round
}

function heightToInches(h) {
  if (!h) return null
  const m = String(h).match(/^(\d+)-(\d+(?:\.\d+)?)$/)
  if (!m) return null
  return parseInt(m[1], 10) * 12 + parseFloat(m[2])
}

function weightToLbs(w) {
  if (!w) return null
  const m = String(w).match(/(\d+(?:\.\d+)?)/)
  return m ? parseFloat(m[1]) : null
}

// ─── icons ──────────────────────────────────────────────────────────────────

function LinkIcon({ className = 'h-3.5 w-3.5' }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
      <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
    </svg>
  )
}

// ─── ReportCard ─────────────────────────────────────────────────────────────

function ReportCard({ report, onShare, copied, responseTime }) {
  const s = report?.stats ?? {}
  const stats = [
    { label: 'PTS', value: formatStat(s.pts), good: typeof s.pts === 'number' && s.pts >= 15 },
    { label: 'REB', value: formatStat(s.reb), good: typeof s.reb === 'number' && s.reb >= 7 },
    { label: 'AST', value: formatStat(s.ast), good: typeof s.ast === 'number' && s.ast >= 4 },
    { label: 'FG%', value: formatStat(s.fg_pct, true), good: typeof s.fg_pct === 'number' && s.fg_pct >= 0.47 },
    { label: '3PT%', value: formatStat(s.three_pct, true), good: typeof s.three_pct === 'number' && s.three_pct >= 0.36 },
    { label: 'FT%', value: formatStat(s.ft_pct, true), good: typeof s.ft_pct === 'number' && s.ft_pct >= 0.78 },
  ]
  const physical = [
    { label: 'Height', value: report?.physical?.height ?? '--' },
    { label: 'Weight', value: report?.physical?.weight ?? '--' },
    { label: 'Wingspan', value: report?.physical?.wingspan ?? '--' },
  ]
  const confidence = typeof report?.confidence === 'number' ? report.confidence : 0
  const theme = getProfileTheme(confidence)
  const meta = [report.position ?? '--', report.team ?? '--', report.age ?? '--'].join('  ·  ')

  return (
    <section className={`${CARD} border-t-4 p-6`} style={{ borderTopColor: theme.border }}>
      <div className="mb-5 border-b border-[#233251] pb-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-3xl font-bold tracking-tight text-[#F3F8FF] sm:text-4xl">
              {report.player_name ?? '--'}
            </h2>
            <p className="mt-1.5 text-sm text-[#94A3B8]">{meta}</p>
          </div>
          {onShare && (
            <div className="relative">
              <button
                type="button"
                onClick={onShare}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[#38BDF8]/40 bg-[#38BDF8]/5 px-3 py-1.5 text-xs font-semibold text-[#7DD3FC] transition hover:border-[#38BDF8] hover:bg-[#38BDF8]/10"
              >
                <LinkIcon />
                Share Report
              </button>
              {copied && (
                <span className="absolute right-0 top-full mt-2 whitespace-nowrap rounded-md border border-[#233251] bg-[#0C1424] px-2 py-1 text-[10px] font-semibold text-[#94A3B8] shadow-lg">
                  Link copied!
                </span>
              )}
            </div>
          )}
        </div>
        <div className="mt-3">
          <span className={`inline-flex rounded-full border px-3 py-1 text-xs font-semibold ${theme.badge}`}>
            {theme.label}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {stats.map((stat) => (
          <div key={stat.label} className={`${TILE} p-3 transition-colors hover:border-[#38BDF8]/40`}>
            <div className="flex items-center gap-1.5">
              <p className="text-xs font-medium uppercase tracking-wider text-[#94A3B8]">{stat.label}</p>
              {stat.good && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[#34D399]" aria-label="strong" />}
            </div>
            <p className="mt-1 text-2xl font-bold text-[#F3F8FF]">{stat.value}</p>
          </div>
        ))}
      </div>

      <div className="mt-4 grid grid-cols-3 gap-3">
        {physical.map((item) => (
          <div key={item.label} className={`${TILE} p-3`}>
            <p className="text-xs font-medium uppercase tracking-wider text-[#94A3B8]">{item.label}</p>
            <p className="mt-1 text-lg font-bold text-[#F3F8FF]">{item.value}</p>
          </div>
        ))}
      </div>

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <div className={`${TILE} border-l-4 border-l-[#34D399] p-4`}>
          <h3 className="mb-3 text-sm font-semibold text-[#34D399]">Strengths</h3>
          <ul className="space-y-2 text-sm text-[#CBD6E6]">
            {(report.strengths ?? []).length > 0 ? (
              report.strengths.map((item, idx) => (
                <li key={idx} className="flex items-start gap-2.5">
                  <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-[#34D399]" />
                  <span>{item}</span>
                </li>
              ))
            ) : (
              <li className="text-[#64748B]">--</li>
            )}
          </ul>
        </div>

        <div className={`${TILE} border-l-4 border-l-[#F87171] p-4`}>
          <h3 className="mb-3 text-sm font-semibold text-[#F87171]">Weaknesses</h3>
          <ul className="space-y-2 text-sm text-[#CBD6E6]">
            {(report.weaknesses ?? []).length > 0 ? (
              report.weaknesses.map((item, idx) => (
                <li key={idx} className="flex items-start gap-2.5">
                  <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-[#F87171]" />
                  <span>{item}</span>
                </li>
              ))
            ) : (
              <li className="text-[#64748B]">--</li>
            )}
          </ul>
        </div>
      </div>

      <div className="mt-6 rounded-lg border border-[#38BDF8]/30 bg-[#38BDF8]/[0.08] p-4">
        <p className="text-xs font-semibold uppercase tracking-wider text-[#7DD3FC]">NBA Comparison</p>
        <p className="mt-1 text-2xl font-bold text-[#F3F8FF]">{report.nba_comp?.name ?? '--'}</p>
        <p className="mt-2 text-sm text-[#94A3B8]">{report.nba_comp?.reasoning ?? '--'}</p>
      </div>

      {report.draft_projection !== null && (
        <div className={`${TILE} mt-6 border-l-4 border-l-[#38BDF8] p-4`}>
          <p className="text-xs font-semibold uppercase tracking-wider text-[#7DD3FC]">Draft Projection</p>
          <p className="mt-1 text-2xl font-bold text-[#F3F8FF]">
            {formatDraftProjectionRound(report.draft_projection?.round)}
            {report.draft_projection?.year !== null && report.draft_projection?.year !== undefined ? (
              <span className="text-[#94A3B8]"> ({report.draft_projection?.year})</span>
            ) : null}
          </p>
          <p className="mt-2 text-sm text-[#94A3B8]">
            {report.draft_projection?.notes?.trim() ? report.draft_projection?.notes : '--'}
          </p>
        </div>
      )}

      <footer className="mt-6 border-t border-[#233251] pt-4 text-xs text-[#64748B]">
        <p>Report generated in {responseTime ?? report.response_time_seconds ?? '--'}s</p>
      </footer>
    </section>
  )
}

// ─── HeadToHeadTable ─────────────────────────────────────────────────────────

function HeadToHeadTable({ r1, r2 }) {
  // highlight=true rows: better stat blue-green, worse stat red-tinted; ties/nulls neutral.
  // highlight=false rows: always neutral, no winner indicated.
  const rows = [
    { label: 'PTS', v1: r1?.stats?.pts, v2: r2?.stats?.pts, fmt: (v) => formatStat(v), highlight: true, cmp: (a, b) => a - b },
    { label: 'REB', v1: r1?.stats?.reb, v2: r2?.stats?.reb, fmt: (v) => formatStat(v), highlight: true, cmp: (a, b) => a - b },
    { label: 'AST', v1: r1?.stats?.ast, v2: r2?.stats?.ast, fmt: (v) => formatStat(v), highlight: true, cmp: (a, b) => a - b },
    { label: 'FG%', v1: r1?.stats?.fg_pct, v2: r2?.stats?.fg_pct, fmt: (v) => formatStat(v, true), highlight: true, cmp: (a, b) => a - b },
    { label: '3PT%', v1: r1?.stats?.three_pct, v2: r2?.stats?.three_pct, fmt: (v) => formatStat(v, true), highlight: true, cmp: (a, b) => a - b },
    { label: 'FT%', v1: r1?.stats?.ft_pct, v2: r2?.stats?.ft_pct, fmt: (v) => formatStat(v, true), highlight: true, cmp: (a, b) => a - b },
    { label: 'Height', v1: r1?.physical?.height, v2: r2?.physical?.height, fmt: (v) => v ?? '--', highlight: false },
    { label: 'Weight', v1: r1?.physical?.weight, v2: r2?.physical?.weight, fmt: (v) => v ?? '--', highlight: false },
    { label: 'Wingspan', v1: r1?.physical?.wingspan, v2: r2?.physical?.wingspan, fmt: (v) => v ?? '--', highlight: false },
  ]

  const win = 'bg-[#34D399]/12 text-[#34D399] font-bold'
  const lose = 'bg-[#F87171]/12 text-[#EAF0FA]'
  const neutral = 'text-[#EAF0FA] font-semibold'

  return (
    <div className={`mb-4 overflow-x-auto ${CARD}`}>
      <div className="min-w-[480px]">
        <div className="grid grid-cols-3 border-b border-[#233251] bg-[#17233E] px-4 py-3 text-xs font-semibold uppercase tracking-wider text-[#94A3B8]">
          <span className="truncate text-[#F3F8FF]">{r1?.player_name ?? 'Player 1'}</span>
          <span className="text-center">Stat</span>
          <span className="truncate text-right text-[#F3F8FF]">{r2?.player_name ?? 'Player 2'}</span>
        </div>
        {rows.map(({ label, v1, v2, fmt, highlight, cmp }) => {
          const bothPresent = highlight && v1 != null && v2 != null
          const diff = bothPresent ? cmp(v1, v2) : 0
          const p1Win = bothPresent && diff > 0
          const p2Win = bothPresent && diff < 0

          const cls1 = !highlight ? neutral : p1Win ? win : p2Win ? lose : neutral
          const cls2 = !highlight ? neutral : p2Win ? win : p1Win ? lose : neutral

          return (
            <div key={label} className="grid grid-cols-3 border-t border-[#233251]">
              <span className={`px-4 py-3 text-sm ${cls1}`}>{fmt(v1)}</span>
              <span className="px-4 py-3 text-center text-xs uppercase tracking-wider text-[#94A3B8]">{label}</span>
              <span className={`px-4 py-3 text-right text-sm ${cls2}`}>{fmt(v2)}</span>
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
  const [placeholderIdx, setPlaceholderIdx] = useState(0)
  const [report, setReport] = useState(null)
  const [error, setError] = useState(null)
  const [copied, setCopied] = useState(false)
  const didAutoRunDeepLink = useRef(false)
  const pollRef = useRef(null)

  // Compare mode state
  const [p1Name, setP1Name] = useState('')
  const [p2Name, setP2Name] = useState('')
  const [compareLoading, setCompareLoading] = useState(false)
  const [comparison, setComparison] = useState(null)
  const [compareError, setCompareError] = useState(null)

  // Recent searches
  const [recentSearches, setRecentSearches] = useState([])

  async function generateReport(nextPlayerName, nextTeamOrSchool) {
    const trimmedPlayer = String(nextPlayerName ?? '').trim()
    const trimmedTeam = String(nextTeamOrSchool ?? '').trim()
    if (!trimmedPlayer) return
    const combinedPlayerName = trimmedTeam ? `${trimmedPlayer} ${trimmedTeam}` : trimmedPlayer

    // Cancel any poll loop still running from a previous search.
    if (pollRef.current) pollRef.current.cancelled = true
    const runState = { cancelled: false }
    pollRef.current = runState

    setLoading(true)
    setError(null)
    setReport(null)
    setElapsed(0)

    const startTime = Date.now()
    const elapsedTimer = setInterval(() => {
      if (runState.cancelled) return
      setElapsed(Math.floor((Date.now() - startTime) / 1000))
    }, 1000)

    const POLL_INTERVAL_MS = 2000
    const TIMEOUT_MS = 90000

    try {
      const response = await fetch(`${API_URL}/scout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ player_name: combinedPlayerName }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data?.detail || 'Failed to generate scouting report')
      const jobId = data?.job_id
      if (!jobId) throw new Error('No job ID returned from server')

      // Poll until the job completes, errors, or we hit the 90s timeout.
      while (!runState.cancelled) {
        if (Date.now() - startTime > TIMEOUT_MS) {
          throw new Error('Scouting timed out after 90 seconds. Please try again.')
        }
        await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS))
        if (runState.cancelled) return

        const pollResp = await fetch(`${API_URL}/scout/${jobId}`)
        const pollData = await pollResp.json().catch(() => ({}))
        if (!pollResp.ok) {
          if (pollResp.status === 404) throw new Error('Scouting job not found.')
          throw new Error(pollData?.detail || 'Failed to fetch scouting status')
        }

        if (pollData.status === 'complete') {
          setReport(pollData.report)
          // Refresh recent searches so the new entry shows if the user clears the report
          fetch(`${API_URL}/recent`)
            .then((r) => (r.ok ? r.json() : null))
            .then((d) => (Array.isArray(d) ? setRecentSearches(d) : null))
            .catch(() => null)
          return
        }
        if (pollData.status === 'error') {
          throw new Error(pollData.detail || 'Scouting failed')
        }
        // status === 'processing' → keep polling
      }
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
    fetch(`${API_URL}/recent`)
      .then((r) => r.ok ? r.json() : [])
      .then((data) => Array.isArray(data) ? setRecentSearches(data) : null)
      .catch(() => null)
  }, [])

  // Rotate the search placeholder through example prospects.
  useEffect(() => {
    const id = setInterval(() => {
      setPlaceholderIdx((i) => (i + 1) % PLACEHOLDER_EXAMPLES.length)
    }, 3000)
    return () => clearInterval(id)
  }, [])

  // Which loading step to highlight, based on elapsed seconds.
  const currentStep = LOADING_STEPS.findIndex((s) => elapsed < s.until)

  const inputCls =
    'h-12 w-full rounded-lg border border-[#233251] bg-[#0C1424] px-4 text-[#EAF0FA] ' +
    'placeholder:text-[#5D6B84] outline-none transition focus:border-[#38BDF8] focus:ring-2 focus:ring-[#38BDF8]/25'

  const primaryBtn =
    'inline-flex h-12 items-center justify-center rounded-lg bg-gradient-to-b from-[#38BDF8] to-[#0EA5E9] px-6 ' +
    'font-semibold text-[#06131F] shadow-lg shadow-[#38BDF8]/25 transition hover:from-[#7DD3FC] hover:to-[#38BDF8] ' +
    'disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none'

  const tabs = [
    { key: 'scout', label: 'Scout Player' },
    { key: 'compare', label: 'Compare Players' },
  ]

  return (
    <div className="relative flex min-h-screen flex-col bg-[#0A0F1C] font-[Inter,system-ui] text-[#EAF0FA]">
      {/* subtle premium glow behind the top of the page */}
      <div className="pointer-events-none fixed inset-x-0 top-0 -z-0 h-72 bg-gradient-to-b from-[#38BDF8]/10 via-[#38BDF8]/[0.03] to-transparent" />

      {/* header bar */}
      <header className="sticky top-0 z-20 border-b border-[#233251] bg-[#0A0F1C]/85 backdrop-blur">
        <div className="mx-auto w-full max-w-[960px] px-4">
          <div className="flex items-center gap-2 pt-5">
            <span className="text-2xl font-bold tracking-tight text-[#F3F8FF]">NBAScout</span>
            <span className="rounded bg-[#38BDF8] px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-[#06131F]">
              AI
            </span>
          </div>
          <p className="mt-1 text-sm text-[#94A3B8]">AI-powered prospect scouting</p>
          <nav className="mt-4 flex gap-6">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                type="button"
                onClick={() => setMode(tab.key)}
                className={`-mb-px border-b-2 px-1 pb-3 pt-1 text-sm font-semibold transition ${
                  mode === tab.key
                    ? 'border-[#38BDF8] text-[#F3F8FF]'
                    : 'border-transparent text-[#94A3B8] hover:text-[#EAF0FA]'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="relative z-10 mx-auto w-full max-w-[960px] flex-1 px-4 py-8">

        {/* ── Scout mode ── */}
        {mode === 'scout' && (
          <>
            <div className={`${CARD} p-6`}>
              <form onSubmit={handleSubmit} className="flex flex-col gap-3">
                <input
                  type="text"
                  value={playerName}
                  onChange={(e) => setPlayerName(e.target.value)}
                  placeholder={`Try: ${PLACEHOLDER_EXAMPLES[placeholderIdx]}…`}
                  className={inputCls}
                  required
                />
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                  <input
                    type="text"
                    value={teamOrSchool}
                    onChange={(e) => setTeamOrSchool(e.target.value)}
                    placeholder="Team or school (optional)"
                    className="h-10 w-full rounded-lg border border-[#233251] bg-[#0C1424] px-3 text-sm text-[#EAF0FA] placeholder:text-[#5D6B84] outline-none transition focus:border-[#38BDF8] focus:ring-2 focus:ring-[#38BDF8]/25 sm:max-w-[320px]"
                  />
                  <button
                    type="submit"
                    disabled={loading || !playerName.trim()}
                    className={`${primaryBtn} w-full sm:w-auto`}
                  >
                    Generate Report
                  </button>
                </div>
              </form>
            </div>

            {!report && !loading && recentSearches.length > 0 && (
              <div className="mt-6">
                <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-[#94A3B8]">
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
                      className="flex items-center gap-1.5 rounded-full border border-[#233251] bg-[#111A2E] px-3 py-1.5 text-sm transition hover:border-[#38BDF8]/50 hover:bg-[#17233E]"
                    >
                      <span className="font-medium text-[#EAF0FA]">{entry.player_name}</span>
                      {entry.position && (
                        <span className="text-xs text-[#7DD3FC]">{entry.position}</span>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {loading && (
              <div className={`${CARD} mt-6 flex flex-col items-center gap-5 p-8`}>
                <div className="h-8 w-8 animate-spin rounded-full border-[3px] border-[#233251] border-t-[#38BDF8]" />
                <ul className="w-full max-w-xs space-y-3">
                  {LOADING_STEPS.map((step, idx) => {
                    const isActive = idx === currentStep
                    const isDone = currentStep > idx
                    return (
                      <li key={step.label} className="flex items-center gap-3">
                        <span
                          className={
                            isActive
                              ? 'h-2.5 w-2.5 shrink-0 animate-pulse rounded-full bg-[#38BDF8]'
                              : isDone
                              ? 'h-2.5 w-2.5 shrink-0 rounded-full bg-[#38BDF8]/40'
                              : 'h-2.5 w-2.5 shrink-0 rounded-full bg-[#233251]'
                          }
                        />
                        <span
                          className={`text-sm ${
                            isActive ? 'font-medium text-[#EAF0FA]' : isDone ? 'text-[#94A3B8]' : 'text-[#5D6B84]'
                          }`}
                        >
                          {step.label}
                        </span>
                      </li>
                    )
                  })}
                </ul>
                <p className="text-xs tabular-nums text-[#94A3B8]">
                  Scouting {playerName}… {elapsed}s
                </p>
              </div>
            )}

            {error && (
              <section className="mt-6 rounded-lg border border-[#F87171]/30 bg-[#F87171]/10 p-4 text-sm text-[#F87171]">
                {error}
              </section>
            )}

            {report && !loading && (
              <div className="mt-6">
                <ReportCard report={report} onShare={handleShare} copied={copied} />
              </div>
            )}
          </>
        )}

        {/* ── Compare mode ── */}
        {mode === 'compare' && (
          <>
            <div className={`${CARD} p-6`}>
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
                  className={`${primaryBtn} w-full sm:w-auto sm:self-start`}
                >
                  Compare Players
                </button>
              </form>
            </div>

            {compareLoading && (
              <div className={`${CARD} mt-6 flex flex-col items-center gap-4 p-8`}>
                <div className="h-8 w-8 animate-spin rounded-full border-[3px] border-[#233251] border-t-[#38BDF8]" />
                <p className="text-sm text-[#94A3B8]">
                  Comparing {p1Name} vs {p2Name}… this takes 30–60 seconds
                </p>
              </div>
            )}

            {compareError && (
              <section className="mt-6 rounded-lg border border-[#F87171]/30 bg-[#F87171]/10 p-4 text-sm text-[#F87171]">
                {compareError}
              </section>
            )}

            {comparison && !compareLoading && (
              <div className="mt-6">
                <HeadToHeadTable r1={comparison.player_one} r2={comparison.player_two} />
                <p className="mb-6 text-center text-xs text-[#64748B]">
                  Comparison generated in {comparison.response_time_seconds ?? '--'}s
                </p>
                <div className="grid gap-6 lg:grid-cols-2">
                  <ReportCard report={comparison.player_one} />
                  <ReportCard report={comparison.player_two} />
                </div>
              </div>
            )}
          </>
        )}

      </main>

      {/* page footer */}
      <footer className="relative z-10 border-t border-[#233251] bg-[#0B1120]">
        <div className="mx-auto flex w-full max-w-[960px] flex-col items-center justify-between gap-3 px-4 py-6 text-sm text-[#94A3B8] sm:flex-row">
          <p>nbascout.app — AI scouting for college and international prospects</p>
          <div className="flex gap-4">
            <a
              href="https://x.com"
              target="_blank"
              rel="noreferrer"
              className="font-medium transition hover:text-[#7DD3FC]"
            >
              Twitter/X
            </a>
            <a
              href="https://github.com"
              target="_blank"
              rel="noreferrer"
              className="font-medium transition hover:text-[#7DD3FC]"
            >
              GitHub
            </a>
          </div>
        </div>
      </footer>
    </div>
  )
}
