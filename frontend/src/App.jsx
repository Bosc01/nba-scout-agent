import { useState } from 'react'
import './App.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function getConfidenceStyle(confidence) {
  if (confidence > 0.7) return 'bg-[#22c55e]/20 text-[#22c55e] border-[#22c55e]/40'
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

export default function App() {
  const [playerName, setPlayerName] = useState('')
  const [loading, setLoading] = useState(false)
  const [report, setReport] = useState(null)
  const [error, setError] = useState(null)

  async function handleSubmit(event) {
    event.preventDefault()
    const trimmed = playerName.trim()
    if (!trimmed) return

    setLoading(true)
    setError(null)
    setReport(null)

    try {
      const response = await fetch(`${API_URL}/scout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ player_name: trimmed }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(data?.detail || 'Failed to generate scouting report')
      }
      setReport(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unexpected error')
    } finally {
      setLoading(false)
    }
  }

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
    <div className="min-h-screen bg-[#0a0a0a] font-[system-ui] text-[#ffffff]">
      <main className="mx-auto w-full max-w-[800px] px-4 py-10">
        <header className="mb-8 text-center">
          <h1 className="text-4xl font-semibold tracking-tight text-[#ffffff]">NBA Scout</h1>
          <p className="mt-2 text-sm text-[#888888]">
            AI-powered scouting reports for college and international prospects
          </p>
        </header>

        <form onSubmit={handleSubmit} className="mb-8 flex flex-col gap-3 sm:flex-row">
          <input
            type="text"
            value={playerName}
            onChange={(e) => setPlayerName(e.target.value)}
            placeholder="Enter player name (e.g. Cooper Flagg)"
            className="h-12 flex-1 rounded-lg border border-[#2a2a2a] bg-[#141414] px-4 text-[#ffffff] placeholder:text-[#888888] outline-none transition focus:border-[#f97316] focus:ring-2 focus:ring-[#f97316]/40"
          />
          <button
            type="submit"
            disabled={loading || !playerName.trim()}
            className="h-12 rounded-lg bg-[#f97316] px-5 font-semibold text-[#0a0a0a] transition hover:bg-[#fb923c] disabled:cursor-not-allowed disabled:opacity-50"
          >
            Generate Report
          </button>
        </form>

        {loading && (
          <section className="mb-6 rounded-lg border border-[#2a2a2a] bg-[#141414] p-4">
            <div className="flex items-center gap-3">
              <span className="h-3 w-3 animate-pulse rounded-full bg-[#f97316]" />
              <p className="text-sm text-[#888888]">Scouting {playerName}... this takes 20-30 seconds</p>
            </div>
          </section>
        )}

        {error && (
          <section className="mb-6 rounded-lg border border-[#ef4444] bg-[#ef4444]/10 p-4 text-sm text-[#ef4444]">
            {error}
          </section>
        )}

        {report && !loading && (
          <section className="rounded-xl border border-[#2a2a2a] bg-[#141414] p-6">
            <div className="mb-5 border-b border-[#2a2a2a] pb-5">
              <h2 className="text-3xl font-semibold text-[#ffffff]">{report.player_name ?? '--'}</h2>
              <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-[#f97316]">
                <span>{report.position ?? '--'}</span>
                <span>{report.team ?? '--'}</span>
                <span>{report.age ?? '--'}</span>
              </div>
              <div className="mt-3">
                <span
                  className={`inline-flex rounded-full border px-3 py-1 text-xs font-semibold ${getConfidenceStyle(
                    confidence
                  )}`}
                >
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

            <footer className="mt-6 border-t border-[#2a2a2a] pt-4 text-xs text-[#888888]">
              <p>Response time: {report.response_time_seconds ?? '--'}s</p>
            </footer>
          </section>
        )}
      </main>
    </div>
  )
}
