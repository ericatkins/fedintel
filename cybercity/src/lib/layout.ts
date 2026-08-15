/**
 * City grid layout.
 *
 * The city is a square grid of parcels. Each parcel holds one repo building.
 * Parcels are separated by streets; each parcel has its own sidewalk apron.
 * Repos are assigned to parcels in a ring spiral from the city center, ordered
 * by importance — rank 1 gets the center parcel and becomes the landmark tower
 * carrying the account name.
 *
 * World units: 1 unit ≈ 1 m. Parcel lot = 26, street = 12 → pitch = 38.
 */
import type { AccountMeta, CityModel, CityRepo, RepoMeta } from './types'
import { scoreRepos, daysSince } from './scoring'
import { languageColor } from './palette'

export const LOT = 26
export const STREET = 12
export const PITCH = LOT + STREET

export const MIN_HEIGHT = 7
export const MAX_HEIGHT = 66

/** Ring-spiral grid coordinates: (0,0), then ring 1 (8 cells), ring 2 (16), ... */
export function spiralCells(count: number): Array<[number, number]> {
  const cells: Array<[number, number]> = [[0, 0]]
  let ring = 1
  while (cells.length < count) {
    const ringCells: Array<[number, number]> = []
    for (let dx = -ring; dx <= ring; dx++)
      for (let dz = -ring; dz <= ring; dz++)
        if (Math.max(Math.abs(dx), Math.abs(dz)) === ring) ringCells.push([dx, dz])
    // stable ordering around the ring: by angle
    ringCells.sort((a, b) => Math.atan2(a[1], a[0]) - Math.atan2(b[1], b[0]))
    cells.push(...ringCells)
    ring++
  }
  return cells.slice(0, count)
}

export function buildCity(account: AccountMeta, repos: RepoMeta[], now = Date.now()): CityModel {
  // Sort out noise: archived forks with zero traction go to the outskirts anyway
  const scores = scoreRepos(repos, now)
  const ranked = [...repos].sort(
    (a, b) => (scores.get(a.id)?.importance ?? 0) < (scores.get(b.id)?.importance ?? 0) ? 1 : -1,
  )
  const cells = spiralCells(ranked.length)

  const cityRepos: CityRepo[] = ranked.map((meta, i) => {
    const s = scores.get(meta.id)!
    const [cx, cz] = cells[i]
    const heightUnits = MIN_HEIGHT + s.height * (MAX_HEIGHT - MIN_HEIGHT)
    const base = 9 + s.footprint * 11 // 9..20, always inside the 26-unit lot
    return {
      meta,
      scores: s,
      x: cx * PITCH,
      z: cz * PITCH,
      heightUnits,
      widthUnits: base,
      depthUnits: base * (0.85 + 0.3 * pseudoRandom(meta.id)),
      accentColor: languageColor(meta.language),
    }
  })

  const maxCell = Math.max(1, ...cells.map(([x, z]) => Math.max(Math.abs(x), Math.abs(z))))
  const halfExtent = (maxCell + 1) * PITCH

  const langCounts = new Map<string, number>()
  for (const r of repos) {
    if (r.language) langCounts.set(r.language, (langCounts.get(r.language) ?? 0) + 1)
  }
  const languages = [...langCounts.entries()]
    .map(([language, count]) => ({ language, count }))
    .sort((a, b) => b.count - a.count)

  return {
    account,
    repos: cityRepos,
    halfExtent,
    totals: {
      stars: repos.reduce((a, r) => a + r.stars, 0),
      forks: repos.reduce((a, r) => a + r.forks, 0),
      watchers: repos.reduce((a, r) => a + r.watchers, 0),
      openIssues: repos.reduce((a, r) => a + r.openIssues, 0),
      languages,
      recentlyActive: repos.filter(r => daysSince(r.pushedAt, now) <= 30).length,
    },
  }
}

/** Deterministic 0..1 from an id, so silhouettes vary but are stable. */
export function pseudoRandom(seed: number): number {
  let x = (seed ^ 0x9e3779b9) >>> 0
  x = Math.imul(x ^ (x >>> 16), 0x45d9f3b) >>> 0
  x = Math.imul(x ^ (x >>> 16), 0x45d9f3b) >>> 0
  return ((x ^ (x >>> 16)) >>> 0) / 0xffffffff
}
