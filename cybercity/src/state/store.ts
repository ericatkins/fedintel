import { create } from 'zustand'
import type { CameraMode, CityModel, Filters } from '../lib/types'
import { fetchAccount, fetchRepos } from '../lib/github'
import { buildCity } from '../lib/layout'
import { MOCK_ACCOUNT, MOCK_REPOS } from '../lib/mock'

interface CityState {
  city: CityModel | null
  loading: boolean
  error: string | null
  source: 'mock' | 'github' | null
  selectedRepoId: number | null
  hoveredRepoId: number | null
  cameraMode: CameraMode
  filters: Filters
  focusRequest: { x: number; z: number; nonce: number } | null

  loadMock: () => void
  loadGitHub: (login: string, token?: string) => Promise<void>
  select: (id: number | null) => void
  hover: (id: number | null) => void
  setCameraMode: (m: CameraMode) => void
  setFilters: (f: Partial<Filters>) => void
  focusRepo: (id: number) => void
  resetCamera: () => void
}

export const useCity = create<CityState>((set, get) => ({
  city: null,
  loading: false,
  error: null,
  source: null,
  selectedRepoId: null,
  hoveredRepoId: null,
  cameraMode: 'orbit',
  filters: { language: null, query: '', sortBy: 'importance' },
  focusRequest: null,

  loadMock: () => {
    set({
      city: buildCity(MOCK_ACCOUNT, MOCK_REPOS),
      source: 'mock',
      error: null,
      selectedRepoId: null,
      filters: { language: null, query: '', sortBy: 'importance' },
    })
  },

  loadGitHub: async (login, token) => {
    set({ loading: true, error: null })
    try {
      const account = await fetchAccount(login, { token })
      const repos = await fetchRepos(account.login, account.type, { token })
      if (repos.length === 0) throw new Error(`${account.login} has no visible repositories`)
      set({
        city: buildCity(account, repos),
        source: 'github',
        loading: false,
        selectedRepoId: null,
        filters: { language: null, query: '', sortBy: 'importance' },
      })
    } catch (e: any) {
      set({ loading: false, error: e?.message ?? 'failed to load GitHub data' })
    }
  },

  select: id => set({ selectedRepoId: id }),
  hover: id => set({ hoveredRepoId: id }),
  setCameraMode: m => set({ cameraMode: m }),
  setFilters: f => set(s => ({ filters: { ...s.filters, ...f } })),
  focusRepo: id => {
    const city = get().city
    const repo = city?.repos.find(r => r.meta.id === id)
    if (!repo) return
    set(s => ({
      selectedRepoId: id,
      focusRequest: { x: repo.x, z: repo.z, nonce: (s.focusRequest?.nonce ?? 0) + 1 },
    }))
  },
  resetCamera: () =>
    set(s => ({ focusRequest: { x: 0, z: 0, nonce: (s.focusRequest?.nonce ?? 0) + 1 }, cameraMode: 'orbit' })),
}))

/** Repos passing the active language/search filter; dimmed-out repos still render. */
export function repoMatchesFilters(city: CityModel, filters: Filters, id: number): boolean {
  const repo = city.repos.find(r => r.meta.id === id)
  if (!repo) return false
  if (filters.language && repo.meta.language !== filters.language) return false
  if (filters.query && !repo.meta.name.toLowerCase().includes(filters.query.toLowerCase())) return false
  return true
}
