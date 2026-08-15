/** Demo data so the city renders instantly without hitting the GitHub API. */
import type { AccountMeta, RepoMeta } from './types'
import { windowsFromWeekly } from './activity'

const now = Date.now()
const daysAgo = (d: number) => new Date(now - d * 86_400_000).toISOString()

export const MOCK_ACCOUNT: AccountMeta = {
  login: 'dev_architect',
  name: 'Dev Architect',
  bio: 'Building the future, one commit at a time.',
  avatarUrl: null,
  type: 'User',
  followers: 342,
  following: 87,
  publicRepos: 10,
  htmlUrl: 'https://github.com',
  createdAt: daysAgo(2400),
}

interface M {
  name: string
  desc: string
  lang: string
  stars: number
  forks: number
  watchers: number
  size: number
  issues: number
  pushedDaysAgo: number
}

const MOCKS: M[] = [
  { name: 'aurora-engine', desc: 'Real-time 3D engine built for the future.', lang: 'C++', stars: 2300, forks: 410, watchers: 180, size: 48210, issues: 64, pushedDaysAgo: 0.1 },
  { name: 'nova-api', desc: 'Scalable REST & GraphQL backend.', lang: 'TypeScript', stars: 1100, forks: 205, watchers: 96, size: 12400, issues: 31, pushedDaysAgo: 0.4 },
  { name: 'dataflow', desc: 'Stream processing & analytics.', lang: 'Python', stars: 856, forks: 142, watchers: 71, size: 9800, issues: 22, pushedDaysAgo: 1.2 },
  { name: 'ml-workbench', desc: 'ML experiments & model training.', lang: 'Python', stars: 642, forks: 98, watchers: 54, size: 22100, issues: 17, pushedDaysAgo: 2 },
  { name: 'ui-kit', desc: 'Reusable UI components & design system.', lang: 'TypeScript', stars: 512, forks: 76, watchers: 44, size: 5400, issues: 12, pushedDaysAgo: 3 },
  { name: 'mobile-hub', desc: 'Cross-platform mobile app framework.', lang: 'Dart', stars: 421, forks: 61, watchers: 35, size: 8600, issues: 9, pushedDaysAgo: 6 },
  { name: 'devops-suite', desc: 'CI/CD, infra as code & automation.', lang: 'Go', stars: 367, forks: 52, watchers: 30, size: 4100, issues: 7, pushedDaysAgo: 9 },
  { name: 'docs-portal', desc: 'Documentation & knowledge base.', lang: 'JavaScript', stars: 210, forks: 25, watchers: 18, size: 2100, issues: 4, pushedDaysAgo: 15 },
  { name: 'chat-core', desc: 'Real-time chat microservice.', lang: 'Go', stars: 128, forks: 19, watchers: 12, size: 1800, issues: 3, pushedDaysAgo: 28 },
  { name: 'playground', desc: 'Sandbox & experiments.', lang: 'HTML', stars: 54, forks: 6, watchers: 4, size: 600, issues: 1, pushedDaysAgo: 60 },
]

/** Deterministic 52-week commit pattern: busier for recently pushed repos. */
function mockWeekly(seed: number, pushedDaysAgo: number): number[] {
  const base = Math.max(0.4, 16 - pushedDaysAgo / 4)
  return Array.from({ length: 52 }, (_, i) => {
    const wave = 0.55 + 0.45 * Math.sin(i / 2.6 + seed * 1.7)
    const ramp = 0.35 + 0.65 * (i / 51) // busier toward the present
    const quiet = pushedDaysAgo > 45 && i > 44 ? 0 : 1 // stale repos go quiet
    return Math.round(base * wave * ramp * quiet)
  })
}

/** Synthetic large account for scale testing: `?demo=big` → N repos. */
export function makeBigMock(count: number): { account: AccountMeta; repos: RepoMeta[] } {
  const langs = ['TypeScript', 'Python', 'Go', 'Rust', 'C++', 'JavaScript', 'Ruby', 'Java', 'Shell', 'Dart']
  const nouns = ['engine', 'api', 'kit', 'flow', 'core', 'hub', 'lab', 'grid', 'forge', 'nexus', 'pulse', 'stack']
  const adjs = ['aurora', 'nova', 'quantum', 'hyper', 'neon', 'cyber', 'astro', 'flux', 'zero', 'omega', 'delta', 'vertex']
  const repos: RepoMeta[] = Array.from({ length: count }, (_, i) => {
    const r = (n: number) => {
      // deterministic hash-ish stream per repo index
      let x = ((i + 1) * 2654435761 + n * 40503) >>> 0
      x = Math.imul(x ^ (x >>> 15), 2246822519) >>> 0
      return ((x ^ (x >>> 13)) >>> 0) / 0xffffffff
    }
    const pushedDaysAgo = Math.pow(r(1), 2) * 400
    const stars = Math.round(Math.pow(r(2), 3) * 5000)
    const weekly = mockWeekly(i, pushedDaysAgo)
    return {
      id: 5000 + i,
      name: `${adjs[i % adjs.length]}-${nouns[(i * 7) % nouns.length]}${i >= 144 ? `-${i}` : i >= 24 ? `-${Math.floor(i / 24)}` : ''}`,
      fullName: `mega_org/repo${i}`,
      owner: 'mega_org',
      description: 'Synthetic scale-test repository.',
      stars,
      forks: Math.round(stars * (0.1 + r(3) * 0.2)),
      watchers: Math.round(stars * 0.08),
      openIssues: Math.round(r(4) * 80),
      language: langs[(i * 3) % langs.length],
      sizeKb: Math.round(Math.pow(r(5), 2) * 60000),
      pushedAt: daysAgo(pushedDaysAgo),
      updatedAt: daysAgo(pushedDaysAgo),
      createdAt: daysAgo(500 + r(6) * 1500),
      isFork: false,
      isArchived: r(7) > 0.92,
      defaultBranch: 'main',
      htmlUrl: 'https://github.com',
      activity: { weekly, ...windowsFromWeekly(weekly), fetchedAt: now },
    }
  })
  return {
    account: {
      login: 'mega_org',
      name: 'Mega Org',
      bio: `Scale test district — ${count} repositories.`,
      avatarUrl: null,
      type: 'Organization',
      followers: 12800,
      following: 0,
      publicRepos: count,
      htmlUrl: 'https://github.com',
      createdAt: daysAgo(3000),
    },
    repos,
  }
}

export const MOCK_REPOS: RepoMeta[] = MOCKS.map((m, i) => ({
  id: 1000 + i,
  name: m.name,
  fullName: `${MOCK_ACCOUNT.login}/${m.name}`,
  owner: MOCK_ACCOUNT.login,
  description: m.desc,
  stars: m.stars,
  forks: m.forks,
  watchers: m.watchers,
  openIssues: m.issues,
  language: m.lang,
  sizeKb: m.size,
  pushedAt: daysAgo(m.pushedDaysAgo),
  updatedAt: daysAgo(m.pushedDaysAgo),
  createdAt: daysAgo(900 - i * 40),
  isFork: false,
  isArchived: false,
  defaultBranch: 'main',
  htmlUrl: `https://github.com/${MOCK_ACCOUNT.login}/${m.name}`,
  activity: (() => {
    const weekly = mockWeekly(i, m.pushedDaysAgo)
    return { weekly, ...windowsFromWeekly(weekly), fetchedAt: now }
  })(),
}))
