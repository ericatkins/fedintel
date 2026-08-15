import { useEffect } from 'react'
import { useCity } from './state/store'
import CityScene from './components/CityScene'
import HUD, { LegendPanel } from './components/HUD'
import RepoPanel from './components/RepoPanel'
import ControlsBar from './components/ControlsBar'
import ConnectScreen from './components/ConnectScreen'

export default function App() {
  const { city, loadGitHub, loadMock } = useCity()

  // shareable URLs: ?user=<login> generates that account's city on load
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const user = params.get('user') ?? params.get('org')
    if (user) loadGitHub(user)
    else if (params.get('demo') !== null) loadMock()
  }, [loadGitHub, loadMock])

  if (!city) return <ConnectScreen />

  const share = () => {
    const url = `${window.location.origin}${window.location.pathname}?user=${encodeURIComponent(city.account.login)}`
    navigator.clipboard?.writeText(url)
  }

  return (
    <div className="world">
      <CityScene city={city} />
      <HUD city={city} />
      <LegendPanel city={city} />
      <RepoPanel city={city} />
      <ControlsBar
        city={city}
        onDisconnect={() => {
          history.replaceState(null, '', window.location.pathname)
          useCity.setState({ city: null, source: null, selectedRepoId: null, error: null })
        }}
      />
      <button className="share-btn" onClick={share} title="Copy shareable link">
        ⧉ SHARE CITY
      </button>
    </div>
  )
}
