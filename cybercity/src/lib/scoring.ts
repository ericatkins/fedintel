/**
 * Visualization scoring model — documented and deterministic.
 *
 * All raw metrics are normalized with a log scale so one giant repo does not
 * flatten the rest of the city:
 *
 *   n(x) = log10(1 + x) / log10(1 + max_x_across_repos)
 *
 * Default weighting formulas (from the product spec):
 *
 *   height    = 0.60 * n(stars) + 0.40 * n(forks)
 *   glow      = 0.50 * recent_push + 0.30 * frequency_proxy + 0.20 * recency
 *   footprint = 0.50 * n(size_kb) + 0.25 * n(watchers) + 0.25 * n(stars)
 *   busyness  = 0.40 * recency + 0.30 * n(watchers) + 0.30 * n(open_issues)
 *
 * Activity terms are derived from pushed_at / updated_at timestamps only
 * (metadata — never commit contents):
 *
 *   recency        = exp(-days_since_push / 30)      — half-life ~3 weeks
 *   recent_push    = 1 if pushed within 7d, 0.6 within 30d, 0.25 within 90d, else ~0
 *   frequency_proxy= exp(-days_since_update / 60)    — smoother, longer window
 *
 * importance (parcel placement, center = most important):
 *   importance = 0.45 * height + 0.30 * footprint + 0.25 * glow
 */
import type { RepoMeta, RepoScores } from './types'

const DAY_MS = 86_400_000

export function daysSince(iso: string | null, now = Date.now()): number {
  if (!iso) return 3650
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return 3650
  return Math.max(0, (now - t) / DAY_MS)
}

function logNorm(value: number, max: number): number {
  if (max <= 0) return 0
  return Math.log10(1 + Math.max(0, value)) / Math.log10(1 + max)
}

export function recencyScore(daysSincePush: number): number {
  return Math.exp(-daysSincePush / 30)
}

export function recentPushScore(daysSincePush: number): number {
  if (daysSincePush <= 7) return 1
  if (daysSincePush <= 30) return 0.6
  if (daysSincePush <= 90) return 0.25
  return Math.exp(-daysSincePush / 365) * 0.1
}

export function frequencyProxy(daysSinceUpdate: number): number {
  return Math.exp(-daysSinceUpdate / 60)
}

export function scoreRepos(repos: RepoMeta[], now = Date.now()): Map<number, RepoScores> {
  const maxStars = Math.max(...repos.map(r => r.stars), 0)
  const maxForks = Math.max(...repos.map(r => r.forks), 0)
  const maxWatchers = Math.max(...repos.map(r => r.watchers), 0)
  const maxSize = Math.max(...repos.map(r => r.sizeKb), 0)
  const maxIssues = Math.max(...repos.map(r => r.openIssues), 0)

  const out = new Map<number, RepoScores>()
  const scored = repos.map(r => {
    const nStars = logNorm(r.stars, maxStars)
    const nForks = logNorm(r.forks, maxForks)
    const nWatchers = logNorm(r.watchers, maxWatchers)
    const nSize = logNorm(r.sizeKb, maxSize)
    const nIssues = logNorm(r.openIssues, maxIssues)

    const dPush = daysSince(r.pushedAt, now)
    const dUpdate = daysSince(r.updatedAt, now)
    const recency = recencyScore(dPush)

    const height = 0.6 * nStars + 0.4 * nForks
    const glow = 0.5 * recentPushScore(dPush) + 0.3 * frequencyProxy(dUpdate) + 0.2 * recency
    const footprint = 0.5 * nSize + 0.25 * nWatchers + 0.25 * nStars
    const busyness = 0.4 * recency + 0.3 * nWatchers + 0.3 * nIssues
    const importance = 0.45 * height + 0.3 * footprint + 0.25 * glow

    return { id: r.id, s: { height, glow, footprint, busyness, importance, rank: 0 } }
  })

  scored
    .sort((a, b) => b.s.importance - a.s.importance)
    .forEach((entry, i) => {
      entry.s.rank = i + 1
      out.set(entry.id, entry.s)
    })
  return out
}
