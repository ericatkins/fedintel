import { useState } from 'react'
import { useCity } from '../state/store'

/**
 * Entry gate: generate a city from any public GitHub user/org, with an
 * optional personal access token (kept in memory only, sent only to
 * api.github.com) — or explore the demo city instantly.
 */
export default function ConnectScreen() {
  const { loadMock, loadGitHub, loading, error } = useCity()
  const [login, setLogin] = useState('')
  const [token, setToken] = useState('')
  const [showToken, setShowToken] = useState(false)

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (login.trim()) loadGitHub(login.trim(), token.trim() || undefined)
  }

  return (
    <div className="connect">
      <div className="connect-card">
        <div className="connect-logo">◈</div>
        <h1>GITHUB CYBER CITY</h1>
        <p className="connect-tag">Your GitHub footprint as a living cyberpunk metropolis.</p>
        <p className="connect-sub">
          Metadata only — repo names, stars, forks, activity timestamps. Source code is never read.
        </p>

        <form onSubmit={submit}>
          <input
            value={login}
            onChange={e => setLogin(e.target.value)}
            placeholder="github username or org…"
            spellCheck={false}
            autoFocus
          />
          {showToken ? (
            <input
              value={token}
              onChange={e => setToken(e.target.value)}
              placeholder="optional token (higher rate limits)"
              type="password"
              spellCheck={false}
            />
          ) : (
            <button type="button" className="connect-tokentoggle" onClick={() => setShowToken(true)}>
              + add access token (optional, raises rate limits)
            </button>
          )}
          <button type="submit" className="connect-go" disabled={loading || !login.trim()}>
            {loading ? 'GENERATING CITY…' : 'GENERATE MY CITY ▶'}
          </button>
        </form>

        {error && <div className="connect-error">⚠ {error}</div>}

        <button className="connect-demo" onClick={() => loadMock()}>
          or explore the demo city
        </button>

        <div className="connect-footer">EVERY COMMIT BUILDS THE FUTURE</div>
      </div>
    </div>
  )
}
