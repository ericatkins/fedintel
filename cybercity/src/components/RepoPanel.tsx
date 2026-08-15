import type { CityModel } from '../lib/types'
import { compact } from '../lib/billboard'
import { daysSince } from '../lib/scoring'
import { useCity } from '../state/store'

/** Right-side inspector shown when a building is clicked. */
export default function RepoPanel({ city }: { city: CityModel }) {
  const { selectedRepoId, select } = useCity()
  const repo = city.repos.find(r => r.meta.id === selectedRepoId)
  if (!repo) return null
  const m = repo.meta
  const s = repo.scores
  const dPush = daysSince(m.pushedAt)

  return (
    <div className="repo-panel">
      <button className="repo-close" onClick={() => select(null)}>✕</button>
      <div className="repo-rank" style={{ color: repo.accentColor }}>{String(s.rank).padStart(2, '0')}</div>
      <div className="repo-name">{m.name.toUpperCase()}</div>
      <div className="repo-owner">{m.owner}{m.isArchived ? ' · ARCHIVED' : ''}{m.isFork ? ' · FORK' : ''}</div>
      {m.description && <div className="repo-desc">{m.description}</div>}

      <div className="repo-grid">
        <div><span>★ STARS</span><b>{compact(m.stars)}</b></div>
        <div><span>⎇ FORKS</span><b>{compact(m.forks)}</b></div>
        <div><span>WATCHERS</span><b>{compact(m.watchers)}</b></div>
        <div><span>OPEN ISSUES</span><b>{compact(m.openIssues)}</b></div>
        <div><span>SIZE</span><b>{m.sizeKb >= 1024 ? `${(m.sizeKb / 1024).toFixed(1)} MB` : `${m.sizeKb} KB`}</b></div>
        <div><span>LAST PUSH</span><b>{dPush < 1 ? 'today' : `${Math.round(dPush)}d ago`}</b></div>
      </div>

      <div className="repo-section">CITY ENCODING</div>
      <ScoreBar label="HEIGHT · stars+forks" value={s.height} color="#a855f7" />
      <ScoreBar label="GLOW · recent activity" value={s.glow} color="#22d3ee" />
      <ScoreBar label="FOOTPRINT · size+reach" value={s.footprint} color="#e879f9" />
      <ScoreBar label="BUSYNESS · traffic" value={s.busyness} color="#fb923c" />

      <div className="repo-tags">
        {m.language && <span style={{ borderColor: repo.accentColor, color: repo.accentColor }}>{m.language}</span>}
        <span>branch: {m.defaultBranch}</span>
      </div>

      <a className="repo-link" href={m.htmlUrl} target="_blank" rel="noreferrer">
        OPEN ON GITHUB ↗
      </a>
    </div>
  )
}

function ScoreBar({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="scorebar">
      <div className="scorebar-label">
        <span>{label}</span>
        <span>{Math.round(value * 100)}</span>
      </div>
      <div className="scorebar-track">
        <div style={{ width: `${Math.round(value * 100)}%`, background: color, boxShadow: `0 0 8px ${color}` }} />
      </div>
    </div>
  )
}
