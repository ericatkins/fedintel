import type { CityModel } from '../lib/types'
import { useCity } from '../state/store'

/** Bottom control deck: search, language filter, camera modes, reset. */
export default function ControlsBar({ city, onDisconnect }: { city: CityModel; onDisconnect: () => void }) {
  const { filters, setFilters, cameraMode, setCameraMode, resetCamera, focusRepo } = useCity()

  const matches = filters.query
    ? city.repos.filter(r => r.meta.name.toLowerCase().includes(filters.query.toLowerCase())).slice(0, 5)
    : []

  return (
    <div className="controls">
      <div className="controls-search">
        <input
          value={filters.query}
          onChange={e => setFilters({ query: e.target.value })}
          placeholder="SEARCH REPO…"
          spellCheck={false}
        />
        {matches.length > 0 && (
          <div className="controls-suggest">
            {matches.map(r => (
              <button key={r.meta.id} onClick={() => { focusRepo(r.meta.id); setFilters({ query: '' }) }}>
                <span style={{ color: r.accentColor }}>▮</span> {r.meta.name}
              </button>
            ))}
          </div>
        )}
      </div>

      <select
        value={filters.language ?? ''}
        onChange={e => setFilters({ language: e.target.value || null })}
      >
        <option value="">ALL LANGUAGES</option>
        {city.totals.languages.map(l => (
          <option key={l.language} value={l.language}>
            {l.language.toUpperCase()} ({l.count})
          </option>
        ))}
      </select>

      <div className="controls-modes">
        {(['orbit', 'street', 'cinematic'] as const).map(m => (
          <button key={m} className={cameraMode === m ? 'active' : ''} onClick={() => setCameraMode(m)}>
            {m.toUpperCase()}
          </button>
        ))}
        <button onClick={resetCamera}>RESET</button>
      </div>

      <button className="controls-disconnect" onClick={onDisconnect}>⏻ NEW CITY</button>
    </div>
  )
}
