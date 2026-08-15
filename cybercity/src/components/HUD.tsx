import { useMemo } from 'react'
import type { CityModel } from '../lib/types'
import { compact } from '../lib/billboard'
import { daysSince } from '../lib/scoring'
import { languageColor } from '../lib/palette'
import { useCity } from '../state/store'

function timeAgo(iso: string | null): string {
  const d = daysSince(iso)
  if (d < 1 / 24) return 'just now'
  if (d < 1) return `${Math.round(d * 24)}h ago`
  if (d < 30) return `${Math.round(d)}d ago`
  if (d < 365) return `${Math.round(d / 30)}mo ago`
  return `${Math.round(d / 365)}y ago`
}

/** Top-left account HUD — identity, totals, language mix, recent activity feed. */
export default function HUD({ city }: { city: CityModel }) {
  const { focusRepo } = useCity()
  const a = city.account
  const t = city.totals

  const recent = useMemo(
    () =>
      [...city.repos]
        .sort((x, y) => daysSince(x.meta.pushedAt) - daysSince(y.meta.pushedAt))
        .slice(0, 5),
    [city],
  )

  const topLangs = t.languages.slice(0, 5)
  const langTotal = Math.max(1, topLangs.reduce((s, l) => s + l.count, 0))

  return (
    <div className="hud hud-left">
      <div className="hud-title">
        <span className="hud-badge">◈</span> GITHUB CYBER CITY
      </div>
      <div className="hud-identity">
        {a.avatarUrl ? (
          <img className="hud-avatar" src={a.avatarUrl} alt="" />
        ) : (
          <div className="hud-avatar hud-avatar-fallback">{a.login.slice(0, 2).toUpperCase()}</div>
        )}
        <div>
          <div className="hud-login">{a.login}</div>
          <div className="hud-bio">{a.bio ?? (a.type === 'Organization' ? 'Organization district' : 'Building the future, one commit at a time.')}</div>
        </div>
      </div>

      <div className="hud-stats">
        <Stat label="REPOSITORIES" value={String(city.repos.length)} />
        <Stat label="FOLLOWERS" value={compact(a.followers)} />
        <Stat label="TOTAL STARS" value={compact(t.stars)} />
        <Stat label="TOTAL FORKS" value={compact(t.forks)} />
        <Stat label="WATCHERS" value={compact(t.watchers)} />
        <Stat label="ACTIVE 30D" value={String(t.recentlyActive)} />
      </div>

      <div className="hud-section">LANGUAGE MIX</div>
      <div className="hud-langbar">
        {topLangs.map(l => (
          <span
            key={l.language}
            style={{ width: `${(l.count / langTotal) * 100}%`, background: languageColor(l.language) }}
            title={`${l.language} × ${l.count}`}
          />
        ))}
      </div>
      <div className="hud-langlist">
        {topLangs.map(l => (
          <span key={l.language}>
            <i style={{ background: languageColor(l.language) }} /> {l.language}
          </span>
        ))}
      </div>

      <div className="hud-section">RECENT ACTIVITY</div>
      <div className="hud-feed">
        {recent.map(r => (
          <button key={r.meta.id} className="hud-feed-row" onClick={() => focusRepo(r.meta.id)}>
            <span className="hud-feed-dot" style={{ background: r.accentColor }} />
            <span className="hud-feed-name">{r.meta.name}</span>
            <span className="hud-feed-time">{timeAgo(r.meta.pushedAt)}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="hud-stat">
      <span className="hud-stat-label">{label}</span>
      <span className="hud-stat-value">{value}</span>
    </div>
  )
}

/** Top-right: commit-traffic legend + system status, echoing the reference art. */
export function LegendPanel({ city }: { city: CityModel }) {
  return (
    <div className="hud hud-right">
      <div className="hud-section" style={{ marginTop: 0 }}>COMMIT TRAFFIC</div>
      <div className="legend-row"><i style={{ background: '#f472b6' }} /> HIGH ACTIVITY</div>
      <div className="legend-row"><i style={{ background: '#fb923c' }} /> MEDIUM ACTIVITY</div>
      <div className="legend-row"><i style={{ background: '#22d3ee' }} /> LOW ACTIVITY</div>
      <div className="legend-row"><i style={{ background: '#6366f1' }} /> MAINTENANCE</div>
      <div className="hud-section">SYSTEM STATUS</div>
      <div className="status-pulse">
        <svg viewBox="0 0 120 24" preserveAspectRatio="none">
          <polyline
            points="0,12 18,12 24,4 30,20 36,12 60,12 66,6 72,18 78,12 120,12"
            fill="none"
            stroke="#f472b6"
            strokeWidth="1.6"
          />
        </svg>
      </div>
      <div className="status-ok">ALL SYSTEMS OPERATIONAL</div>
      <div className="status-meta">
        {city.repos.length} districts · {city.totals.recentlyActive} active
      </div>
    </div>
  )
}
