/**
 * Real commit-activity windows — still METADATA ONLY.
 *
 * Source: GET /repos/{owner}/{repo}/stats/participation — 52 weekly commit
 * counts for the default branch (numbers only, no commit contents, messages,
 * or diffs). Windows are derived as:
 *
 *   c7  = commits in the last 1 week
 *   c30 = commits in the last 4 weeks   (~30d)
 *   c90 = commits in the last 13 weeks  (~90d)
 *
 * Rate-limit strategy:
 *   - only the top MAX_ACTIVITY_REPOS repos by importance are enriched
 *   - results are cached in localStorage for CACHE_TTL_MS (6h)
 *   - fetches run with small concurrency; a 403/429 aborts the remainder
 *   - GitHub returns 202 while it computes stats — retried briefly, then
 *     skipped (scoring falls back to timestamp proxies for that repo)
 */
import type { RepoActivity, RepoMeta } from './types'

const API = 'https://api.github.com'
export const MAX_ACTIVITY_REPOS = 30
const CACHE_TTL_MS = 6 * 3600_000
const CONCURRENCY = 5
const ACCEPTED_RETRIES = 3
const ACCEPTED_DELAY_MS = 1400

function cacheKey(fullName: string): string {
  return `cybercity:activity:${fullName}`
}

function readCache(fullName: string): RepoActivity | null {
  try {
    const raw = localStorage.getItem(cacheKey(fullName))
    if (!raw) return null
    const parsed = JSON.parse(raw) as RepoActivity
    if (Date.now() - parsed.fetchedAt > CACHE_TTL_MS) return null
    if (!Array.isArray(parsed.weekly)) return null
    return parsed
  } catch {
    return null
  }
}

function writeCache(fullName: string, activity: RepoActivity): void {
  try {
    localStorage.setItem(cacheKey(fullName), JSON.stringify(activity))
  } catch {
    /* storage full/unavailable — cache is best-effort */
  }
}

export function windowsFromWeekly(weekly: number[]): Pick<RepoActivity, 'c7' | 'c30' | 'c90'> {
  const sumLast = (n: number) => weekly.slice(-n).reduce((a, b) => a + b, 0)
  return { c7: sumLast(1), c30: sumLast(4), c90: sumLast(13) }
}

const sleep = (ms: number) => new Promise(r => setTimeout(r, ms))

class RateLimitError extends Error {}

async function fetchParticipation(fullName: string, token?: string): Promise<RepoActivity | null> {
  const headers: Record<string, string> = {
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
  }
  if (token) headers.Authorization = `Bearer ${token}`

  for (let attempt = 0; attempt <= ACCEPTED_RETRIES; attempt++) {
    const res = await fetch(`${API}/repos/${fullName}/stats/participation`, { headers })
    if (res.status === 202) {
      // stats are being computed server-side; give GitHub a moment
      await sleep(ACCEPTED_DELAY_MS)
      continue
    }
    if (res.status === 403 || res.status === 429) throw new RateLimitError('rate limited')
    if (!res.ok) return null
    const data = await res.json()
    const weekly: number[] = Array.isArray(data?.all) ? data.all : []
    if (weekly.length === 0) return null
    const activity: RepoActivity = { weekly, ...windowsFromWeekly(weekly), fetchedAt: Date.now() }
    writeCache(fullName, activity)
    return activity
  }
  return null
}

export interface ActivityProgress {
  done: number
  total: number
  rateLimited: boolean
}

/**
 * Enrich up to MAX_ACTIVITY_REPOS repos (assumed pre-sorted by importance)
 * with real commit windows. Calls onProgress as results land so the UI can
 * show sync state; returns a map of repo id → activity.
 */
export async function fetchActivityBatch(
  repos: RepoMeta[],
  token: string | undefined,
  onProgress: (p: ActivityProgress) => void,
): Promise<Map<number, RepoActivity>> {
  const targets = repos.slice(0, MAX_ACTIVITY_REPOS)
  const out = new Map<number, RepoActivity>()
  let done = 0
  let rateLimited = false

  // serve cache hits synchronously
  const misses: RepoMeta[] = []
  for (const r of targets) {
    const cached = readCache(r.fullName)
    if (cached) {
      out.set(r.id, cached)
      done++
    } else {
      misses.push(r)
    }
  }
  onProgress({ done, total: targets.length, rateLimited })

  let cursor = 0
  const worker = async () => {
    while (cursor < misses.length && !rateLimited) {
      const repo = misses[cursor++]
      try {
        const activity = await fetchParticipation(repo.fullName, token)
        if (activity) out.set(repo.id, activity)
      } catch (e) {
        if (e instanceof RateLimitError) rateLimited = true
      }
      done++
      onProgress({ done, total: targets.length, rateLimited })
    }
  }
  await Promise.all(Array.from({ length: Math.min(CONCURRENCY, misses.length) }, worker))
  return out
}
