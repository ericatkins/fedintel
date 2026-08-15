/**
 * GitHub metadata client — METADATA ONLY.
 *
 * Endpoints used (REST v3):
 *   GET /users/{login}            — account profile metadata
 *   GET /orgs/{login}             — org profile metadata (fallback)
 *   GET /users/{login}/repos      — repo listing metadata
 *   GET /orgs/{login}/repos       — org repo listing metadata
 *
 * We intentionally never call contents, git trees, blobs, code search, or any
 * endpoint that returns source code. Only listing/metadata fields are read.
 *
 * Auth: works unauthenticated for public accounts (60 req/hr). An optional
 * fine-grained token raises rate limits and can include the caller's own
 * private repo *metadata*; it is kept in memory only and sent only to
 * api.github.com.
 */
import type { AccountMeta, RepoMeta } from './types'

const API = 'https://api.github.com'

interface FetchOpts {
  token?: string
}

async function ghFetch(path: string, opts: FetchOpts): Promise<Response> {
  const headers: Record<string, string> = {
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
  }
  if (opts.token) headers.Authorization = `Bearer ${opts.token}`
  return fetch(`${API}${path}`, { headers })
}

function mapRepo(r: any): RepoMeta {
  return {
    id: r.id,
    name: r.name,
    fullName: r.full_name,
    owner: r.owner?.login ?? '',
    description: r.description ?? null,
    stars: r.stargazers_count ?? 0,
    forks: r.forks_count ?? 0,
    watchers: r.watchers_count ?? r.subscribers_count ?? 0,
    openIssues: r.open_issues_count ?? 0,
    language: r.language ?? null,
    sizeKb: r.size ?? 0,
    pushedAt: r.pushed_at ?? null,
    updatedAt: r.updated_at ?? null,
    createdAt: r.created_at ?? null,
    isFork: !!r.fork,
    isArchived: !!r.archived,
    defaultBranch: r.default_branch ?? 'main',
    htmlUrl: r.html_url ?? '',
  }
}

export async function fetchAccount(login: string, opts: FetchOpts = {}): Promise<AccountMeta> {
  const res = await ghFetch(`/users/${encodeURIComponent(login)}`, opts)
  if (res.status === 404) throw new Error(`GitHub account "${login}" not found`)
  if (res.status === 403 || res.status === 429) throw new Error('GitHub API rate limit reached — add a token or try later')
  if (!res.ok) throw new Error(`GitHub API error ${res.status}`)
  const u = await res.json()
  return {
    login: u.login,
    name: u.name ?? null,
    bio: u.bio ?? u.description ?? null,
    avatarUrl: u.avatar_url ?? null,
    type: u.type === 'Organization' ? 'Organization' : 'User',
    followers: u.followers ?? 0,
    following: u.following ?? 0,
    publicRepos: u.public_repos ?? 0,
    htmlUrl: u.html_url ?? `https://github.com/${login}`,
    createdAt: u.created_at ?? null,
  }
}

export async function fetchRepos(
  login: string,
  type: 'User' | 'Organization',
  opts: FetchOpts = {},
  maxPages = 4,
): Promise<RepoMeta[]> {
  const base = type === 'Organization' ? `/orgs/${encodeURIComponent(login)}/repos` : `/users/${encodeURIComponent(login)}/repos`
  const repos: RepoMeta[] = []
  for (let page = 1; page <= maxPages; page++) {
    const res = await ghFetch(`${base}?per_page=100&page=${page}&sort=pushed`, opts)
    if (res.status === 403 || res.status === 429) throw new Error('GitHub API rate limit reached — add a token or try later')
    if (!res.ok) break
    const batch = await res.json()
    if (!Array.isArray(batch) || batch.length === 0) break
    repos.push(...batch.map(mapRepo))
    if (batch.length < 100) break
  }
  return repos
}
