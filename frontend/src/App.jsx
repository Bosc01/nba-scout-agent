import { useState } from 'react'
import './App.css'

const API_URL = 'http://localhost:8000/scout'

function confidenceBadgeClass(confidence) {
  const c = typeof confidence === 'number' ? confidence : 0
  if (c > 0.7) return 'bg-[#22c55e]/20 text-[#22c55e] border-[#22c55e]/40'
  if (c >= 0.4) return 'bg-[#eab308]/15 text-[#eab308] border-[#eab308]/35'
  return 'bg-[#ef4444]/15 text-[#ef4444] border-[#ef4444]/35'
}

export default function App() {
  const [playerName, setPlayerName] = useState('')
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function handleScout(e) {
    e.preventDefault()
    const name = playerName.trim()
    if (!name) return

    setLoading(true)
    setError(null)
    setReport(null)

    try {
      const res = await fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ player_name: name }),
      })

      const data = await res.json().catch(() => ({}))

      if (!res.ok) {
        const msg =
          typeof data.detail === 'string'
            ? data.detail
            : Array.isArray(data.detail)
              ? data.detail.map((d) => d.msg || d).join('; ')
              : res.statusText || 'Request failed'
        throw new Error(msg)
      }

      setReport(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  const conf = report?.confidence

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-[#ffffff]">
      <div className="mx-auto flex min-h-screen max-w-2xl flex-col px-4 py-12 sm:py-16">
        <header className="mb-10 text-center">
          <h1 className="text-xl font-semibold tracking-tight text-[#ffffff] sm:text-2xl">
            NBA Scout Agent
          </h1>
          <p className="mt-2 text-sm text-[#888888]">
            Research-backed reports — conservative confidence.
          </p>
        </header>

        <form
          onSubmit={handleScout}
          className="mx-auto flex w-full max-w-md flex-col gap-4"
        >
          <input
            type="text"
            value={playerName}
            onChange={(e) => setPlayerName(e.target.value)}
            placeholder="Enter player name..."
            disabled={loading}
            className="w-full rounded-lg border border-[#2a2a2a] bg-[#141414] px-4 py-3 text-[#ffffff] placeholder:text-[#888888] outline-none ring-[#f97316] transition focus:border-[#f97316] focus:ring-1 disabled:opacity-50"
            aria-label="Player name"
          />
          <button
            type="submit"
            disabled={loading || !playerName.trim()}
            className="rounded-lg bg-[#f97316] px-4 py-3 text-sm font-semibold text-[#0a0a0a] transition hover:bg-[#fb923c] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {loading ? 'Scouting…' : 'Scout'}
          </button>
        </form>

        <div className="mt-10 flex-1">
          {loading && (
            <div
              className="rounded-lg border border-[#2a2a2a] bg-[#141414] p-8 text-center text-sm text-[#888888]"
              role="status"
              aria-live="polite"
            >
              Pulling sources and building report…
            </div>
          )}

          {error && !loading && (
            <div
              className="rounded-lg border border-[#ef4444]/40 bg-[#ef4444]/10 p-6 text-sm text-[#ef4444]"
              role="alert"
            >
              {error}
            </div>
          )}

          {report && !loading && (
            <article className="rounded-lg border border-[#2a2a2a] bg-[#141414] p-6 sm:p-8">
              <div className="flex flex-col gap-3 border-b border-[#2a2a2a] pb-6 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <h2 className="text-lg font-semibold tracking-tight text-[#ffffff]">
                    {report.player_name ?? '—'}
                  </h2>
                  <p className="mt-1 text-sm text-[#888888]">
                    {[report.position, report.team].filter(Boolean).join(' · ') ||
                      '—'}
                  </p>
                </div>
                <span
                  className={`inline-flex shrink-0 items-center rounded-md border px-3 py-1 text-xs font-semibold tabular-nums ${confidenceBadgeClass(conf)}`}
                >
                  Confidence {(typeof conf === 'number' ? conf : 0).toFixed(2)}
                </span>
              </div>

              <div className="mt-6 grid gap-8 sm:grid-cols-2">
                <section>
                  <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[#888888]">
                    Strengths
                  </h3>
                  <ul className="space-y-2 text-sm leading-relaxed text-[#ffffff]">
                    {(report.strengths ?? []).length === 0 ? (
                      <li className="text-[#888888]">No strengths listed.</li>
                    ) : (
                      report.strengths.map((s, i) => (
                        <li key={i} className="flex gap-2">
                          <span
                            className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-[#22c55e]"
                            aria-hidden
                          />
                          <span>{s}</span>
                        </li>
                      ))
                    )}
                  </ul>
                </section>
                <section>
                  <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[#888888]">
                    Weaknesses
                  </h3>
                  <ul className="space-y-2 text-sm leading-relaxed text-[#ffffff]">
                    {(report.weaknesses ?? []).length === 0 ? (
                      <li className="text-[#888888]">No weaknesses listed.</li>
                    ) : (
                      report.weaknesses.map((w, i) => (
                        <li key={i} className="flex gap-2">
                          <span
                            className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-[#ef4444]"
                            aria-hidden
                          />
                          <span>{w}</span>
                        </li>
                      ))
                    )}
                  </ul>
                </section>
              </div>

              <section className="mt-8">
                <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[#888888]">
                  NBA comp
                </h3>
                <div className="rounded-lg border border-[#f97316]/35 bg-[#f97316]/10 p-4 text-sm">
                  <p className="font-semibold text-[#f97316]">
                    {report.nba_comp?.name ?? '—'}
                  </p>
                  <p className="mt-2 leading-relaxed text-[#ffffff]">
                    {report.nba_comp?.reasoning || '—'}
                  </p>
                </div>
              </section>

              <section className="mt-8 border-t border-[#2a2a2a] pt-6">
                <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[#888888]">
                  Sources
                </h3>
                {(report.sources ?? []).length === 0 ? (
                  <p className="text-sm text-[#888888]">No sources linked.</p>
                ) : (
                  <ul className="space-y-2 break-all text-sm">
                    {report.sources.map((url, i) => (
                      <li key={i}>
                        <a
                          href={url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[#f97316] underline decoration-[#f97316]/40 underline-offset-2 hover:text-[#fb923c]"
                        >
                          {url}
                        </a>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </article>
          )}
        </div>
      </div>
    </div>
  )
}
