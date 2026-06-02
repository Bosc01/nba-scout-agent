import { useEffect, useRef, useState } from 'react'
import './App.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// ─── helpers ────────────────────────────────────────────────────────────────

function getConfidenceStyle(confidence) {
  if (confidence >= 0.7) return 'bg-[#22c55e]/20 text-[#22c55e] border-[#22c55e]/40'
  if (confidence >= 0.4) return 'bg-[#eab308]/20 text-[#eab308] border-[#eab308]/40'
  return 'bg-[#888888]/20 text-[#cfcfcf] border-[#888888]/40'
}

function getProfileLabel(confidence) {
  if (confidence >= 0.7) return 'Full Profile'
  if (confidence >= 0.4) return 'Partial Profile'
  return 'Limited Data'
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

// ─── ReportCard ─────────────────────────────────────────────────────────────

function ReportCard({ report, onShare, copied, responseTime }) {
  const stats = [
    { label: 'PTS', value: formatStat(report?.stats?.pts) },
    { label: 'REB', value: formatStat(report?.stats?.reb) },
    { label: 'AST', value: formatStat(report?.stats?.ast) },
    { label: 'FG%', value: formatStat(report?.stats?.fg_pct, true) },
    { label: '3PT%', value: formatStat(report?.stats?.three_pct, true) },
    { label: 'FT%', value: formatStat(report?.stats?.ft_pct, true) },
  ]
  const physical = [
    { label: 'Height', value: report?.physical?.height ?? '--' },
    { label: 'Weight', value: report?.physical?.weight ?? '--' },
    { label: 'Wingspan', value: report?.physical?.wingspan ?? '--' },
  ]
  const confidence = typeof report?.confidence === 'number' ? report.confidence : 0

  return (
    <section className="rounded-xl border border-[#2a2a2a] bg-[#141414] p-6">
      <div className="mb-5 border-b border-[#2a2a2a] pb-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h2 className="text-3xl font-semibold text-[#ffffff]">{report.player_name ?? '--'}</h2>
          {onShare && (
            <div className="relative pt-1">
              <button
                type="button"
                onClick={onShare}
                className="rounded-md border border-[#2a2a2a] bg-[#141414] px-3 py-1 text-xs font-semibold text-[#888888] transition hover:border-[#3a3a3a] hover:text-[#ffffff]"
              >
                Share
              </button>
              {copied && (
                <span className="absolute left-1/2 top-full mt-2 -translate-x-1/2 rounded-md border border-[#2a2a2a] bg-[#101010] px-2 py-1 text-[10px] font-semibold text-[#888888]">
                  Copied!
                </span>
              )}
            </div>
          )}
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-[#f97316]">
          <span>{report.position ?? '--'}</span>
          <span>{report.team ?? '--'}</span>
          <span>{report.age ?? '--'}</span>
        </div>
        <div className="mt-3">
          <span className={`inline-flex rounded-full border px-3 py-1 text-xs font-semibold ${getConfidenceStyle(confidence)}`}>
            {getProfileLabel(confidence)}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {stats.map((stat) => (
          <div key={stat.label} className="rounded-lg border border-[#2a2a2a] bg-[#141414] p-3">
            <p className="text-xs uppercase tracking-wide text-[#888888]">{stat.label}</p>
            <p className="mt-1 text-2xl font-semibold text-[#ffffff]">{stat.value}</p>
          </div>
        ))}
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        {physical.map((item) => (
          <div key={item.label} className="rounded-lg border border-[#2a2a2a] bg-[#141414] p-3">
            <p className="text-xs uppercase tracking-wide text-[#888888]">{item.label}</p>
            <p className="mt-1 text-lg font-semibold text-[#ffffff]">{item.value}</p>
          </div>
        ))}
      </div>

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border-l-4 border-[#22c55e] bg-[#101010] p-4">
          <h3 className="mb-3 text-sm font-semibold text-[#22c55e]">Strengths</h3>
          <ul className="space-y-2 text-sm text-[#ffffff]">
            {(report.strengths ?? []).length > 0 ? (
              report.strengths.map((item, idx) => (
                <li key={idx} className="flex items-start gap-2">
                  <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-[#22c55e]" />
                  <span>{item}</span>
                </li>
              ))
            ) : (
              <li className="text-[#888888]">--</li>
            )}
          </ul>
        </div>

        <div className="rounded-lg border-l-4 border-[#ef4444] bg-[#101010] p-4">
          <h3 className="mb-3 text-sm font-semibold text-[#ef4444]">Weaknesses</h3>
          <ul className="space-y-2 text-sm text-[#ffffff]">
            {(report.weaknesses ?? []).length > 0 ? (
              report.weaknesses.map((item, idx) => (
                <li key={idx} className="flex items-start gap-2">
                  <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-[#ef4444]" />
                  <span>{item}</span>
                </li>
              ))
            ) : (
              <li className="text-[#888888]">--</li>
            )}
          </ul>
        </div>
      </div>

      <div className="mt-6 rounded-lg border border-[#f97316]/50 bg-[#f97316]/10 p-4">
        <p className="text-xs uppercase tracking-wide text-[#f97316]">NBA Comparison</p>
        <p className="mt-1 text-2xl font-semibold text-[#ffffff]">{report.nba_comp?.name ?? '--'}</p>
        <p className="mt-2 text-sm text-[#888888]">{report.nba_comp?.reasoning ?? '--'}</p>
      </div>

      {report.draft_projection !== null && (
        <div className="mt-6 rounded-lg border border-[#f97316]/50 bg-[#f97316]/10 p-4">
          <p className="text-xs uppercase tracking-wide text-[#f97316]">DRAFT PROJECTION</p>
          <p className="mt-1 text-2xl font-semibold text-[#ffffff]">
            {formatDraftProjectionRound(report.draft_projection?.round)}
            {report.draft_projection?.year !== null && report.draft_projection?.year !== undefined ? (
              <span className="text-[#ffffff]/90"> ({report.draft_projection?.year})</span>
            ) : null}
          </p>
          <p className="mt-2 text-sm text-[#888888]">
            {report.draft_projection?.notes?.trim() ? report.draft_projection?.notes : '--'}
          </p>
        </div>
      )}

      <footer className="mt-6 border-t border-[#2a2a2a] pt-4 text-xs text-[#888888]">
        <p>Response time: {responseTime ?? report.response_time_seconds ?? '--'}s</p>
      </footer>
    </section>
  )
}

// ─── HeadToHeadTable ─────────────────────────────────────────────────────────

function HeadToHeadTable({ r1, r2 }) {
  // highlight=true rows: winner orange, loser #888888, null → both white
  // highlight=false rows: always white, no winner indicated
  const rows = [
    {
      label: 'PTS',
      v1: r1?.stats?.pts,
      v2: r2?.stats?.pts,
      fmt: (v) => formatStat(v),
      highlight: true,
      cmp: (a, b) => a - b,
    },
    {
      label: 'REB',
      v1: r1?.stats?.reb,
      v2: r2?.stats?.reb,
      fmt: (v) => formatStat(v),
      highlight: true,
      cmp: (a, b) => a - b,
    },
    {
      label: 'AST',
      v1: r1?.stats?.ast,
      v2: r2?.stats?.ast,
      fmt: (v) => formatStat(v),
      highlight: true,
      cmp: (a, b) => a - b,
    },
    {
      label: 'FG%',
      v1: r1?.stats?.fg_pct,
      v2: r2?.stats?.fg_pct,
      fmt: (v) => formatStat(v, true),
      highlight: true,
      cmp: (a, b) => a - b,
    },
    {
      label: '3PT%',
      v1: r1?.stats?.three_pct,
      v2: r2?.stats?.three_pct,
      fmt: (v) => formatStat(v, true),
      highlight: true,
      cmp: (a, b) => a - b,
    },
    {
      label: 'FT%',
      v1: r1?.stats?.ft_pct,
      v2: r2?.stats?.ft_pct,
      fmt: (v) => formatStat(v, true),
      highlight: true,
      cmp: (a, b) => a - b,
    },
    {
      label: 'Height',
      v1: r1?.physical?.height,
      v2: r2?.physical?.height,
      fmt: (v) => v ?? '--',
      highlight: false,
    },
    {
      label: 'Weight',
      v1: r1?.physical?.weight,
      v2: r2?.physical?.weight,
      fmt: (v) => v ?? '--',
      highlight: false,
    },
    {
      label: 'Wingspan',
      v1: r1?.physical?.wingspan,
      v2: r2?.physical?.wingspan,
      fmt: (v) => v ?? '--',
      highlight: false,
    },
  ]

  return (
    <div className="mb-4 overflow-hidden rounded-xl border border-[#2a2a2a] bg-[#141414]">
      <div className="grid grid-cols-3 border-b border-[#2a2a2a] bg-[#101010] px-4 py-3 text-xs font-semibold uppercase tracking-wide text-[#888888]">
        <span>{r1?.player_name ?? 'Player 1'}</span>
        <span className="text-center">Stat</span>
        <span className="text-right">{r2?.player_name ?? 'Player 2'}</span>
      </div>
      {rows.map(({ label, v1, v2, fmt, highlight, cmp }) => {
        const bothPresent = highlight && v1 != null && v2 != null
        const diff = bothPresent ? cmp(v1, v2) : 0
        const p1Win = bothPresent && diff > 0
        const p2Win = bothPresent && diff < 0

        const cls1 = !highlight
          ? 'text-[#ffffff]'
          : p1Win
          ? 'text-[#f97316]'
          : p2Win
          ? 'text-[#888888]'
          : 'text-[#ffffff]'

        const cls2 = !highlight
          ? 'text-[#ffffff]'
          : p2Win
          ? 'text-[#f97316]'
          : p1Win
          ? 'text-[#888888]'
          : 'text-[#ffffff]'

        return (
          <div
            key={label}
            className="grid grid-cols-3 border-b border-[#2a2a2a] px-4 py-3 last:border-b-0"
          >
            <span className={`text-sm font-semibold ${cls1}`}>{fmt(v1)}</span>
            <span className="text-center text-xs uppercase tracking-wide text-[#888888]">
              {label}
            </span>
            <span className={`text-right text-sm font-semibold ${cls2}`}>{fmt(v2)}</span>
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
  const [report, setReport] = useState(null)
  const [error, setError] = useState(null)
  const [copied, setCopied] = useState(false)
  const didAutoRunDeepLink = useRef(false)

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
    setLoading(true)
    setError(null)
    setReport(null)
    try {
      const response = await fetch(`${API_URL}/scout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ player_name: combinedPlayerName }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data?.detail || 'Failed to generate scouting report')
      setReport(data)
      // Refresh recent searches so the new entry shows if the user clears the report
      fetch(`${API_URL}/recent`)
        .then((r) => r.ok ? r.json() : null)
        .then((d) => Array.isArray(d) ? setRecentSearches(d) : null)
        .catch(() => null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unexpected error')
    } finally {
      setLoading(false)
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

  const inputCls =
    'h-12 w-full rounded-lg border border-[#2a2a2a] bg-[#141414] px-4 text-[#ffffff] ' +
    'placeholder:text-[#888888] outline-none transition focus:border-[#f97316] focus:ring-2 focus:ring-[#f97316]/40'

  return (
    <div className="min-h-screen bg-[#0a0a0a] font-[system-ui] text-[#ffffff]">
      <main className="mx-auto w-full max-w-[900px] px-4 py-10">

        {/* header */}
        <header className="mb-8 text-center">
          <h1 className="text-4xl font-semibold tracking-tight text-[#ffffff]">NBA Scout</h1>
          <p className="mt-2 text-sm text-[#888888]">
            AI-powered scouting reports for college and international prospects
          </p>
        </header>

        {/* mode toggle */}
        <div className="mb-6 flex justify-center">
          <div className="inline-flex rounded-lg border border-[#2a2a2a] bg-[#141414] p-1 gap-1">
            {['scout', 'compare'].map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                className={`rounded-md px-5 py-2 text-sm font-semibold transition ${
                  mode === m
                    ? 'bg-[#f97316] text-[#0a0a0a]'
                    : 'text-[#888888] hover:text-[#ffffff]'
                }`}
              >
                {m === 'scout' ? 'Scout Player' : 'Compare Players'}
              </button>
            ))}
          </div>
        </div>

        {/* ── Scout mode ── */}
        {mode === 'scout' && (
          <>
            <form onSubmit={handleSubmit} className="mb-8 flex flex-col gap-3">
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
                  className="h-10 w-full rounded-lg border border-[#2a2a2a] bg-[#141414] px-3 text-sm text-[#ffffff] placeholder:text-[#888888] outline-none transition focus:border-[#f97316] focus:ring-2 focus:ring-[#f97316]/30 sm:max-w-[320px]"
                />
                <button
                  type="submit"
                  disabled={loading || !playerName.trim()}
                  className="h-12 rounded-lg bg-[#f97316] px-5 font-semibold text-[#0a0a0a] transition hover:bg-[#fb923c] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Generate Report
                </button>
              </div>
            </form>

            {!report && !loading && recentSearches.length > 0 && (
              <div className="mb-6">
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[#888888]">
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
                      className="flex items-center gap-1.5 rounded-full border border-[#2a2a2a] bg-[#141414] px-3 py-1.5 text-sm transition hover:border-[#f97316]/50 hover:bg-[#1a1a1a]"
                    >
                      <span className="font-medium text-[#ffffff]">{entry.player_name}</span>
                      {entry.position && (
                        <span className="text-xs text-[#f97316]">{entry.position}</span>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {loading && (
              <section className="mb-6 rounded-lg border border-[#2a2a2a] bg-[#141414] p-4">
                <div className="flex items-center gap-3">
                  <span className="h-3 w-3 animate-pulse rounded-full bg-[#f97316]" />
                  <p className="text-sm text-[#888888]">Scouting {playerName}… this takes 20–30 seconds</p>
                </div>
              </section>
            )}

            {error && (
              <section className="mb-6 rounded-lg border border-[#ef4444] bg-[#ef4444]/10 p-4 text-sm text-[#ef4444]">
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
            <form onSubmit={handleCompare} className="mb-8 flex flex-col gap-3">
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
                className="h-12 w-full rounded-lg bg-[#f97316] px-5 font-semibold text-[#0a0a0a] transition hover:bg-[#fb923c] disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto sm:self-start"
              >
                Compare
              </button>
            </form>

            {compareLoading && (
              <section className="mb-6 rounded-lg border border-[#2a2a2a] bg-[#141414] p-4">
                <div className="flex items-center gap-3">
                  <span className="h-3 w-3 animate-pulse rounded-full bg-[#f97316]" />
                  <p className="text-sm text-[#888888]">
                    Comparing {p1Name} vs {p2Name}… this takes 30–60 seconds
                  </p>
                </div>
              </section>
            )}

            {compareError && (
              <section className="mb-6 rounded-lg border border-[#ef4444] bg-[#ef4444]/10 p-4 text-sm text-[#ef4444]">
                {compareError}
              </section>
            )}

            {comparison && !compareLoading && (
              <>
                <HeadToHeadTable r1={comparison.player_one} r2={comparison.player_two} />
                <p className="mb-6 text-center text-xs text-[#888888]">
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
    </div>
  )
}
