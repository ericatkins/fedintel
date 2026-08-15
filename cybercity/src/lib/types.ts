/**
 * GitHub Cyber City — metadata-only types.
 *
 * HARD RULE: this app never reads, stores, or reasons about source code.
 * Everything below is high-level repository/account metadata exposed by the
 * GitHub REST API's repo/user listing endpoints.
 */

export interface RepoMeta {
  id: number
  name: string
  fullName: string
  owner: string
  description: string | null
  stars: number
  forks: number
  watchers: number
  openIssues: number
  language: string | null
  /** repo size in KB, as reported by GitHub */
  sizeKb: number
  pushedAt: string | null
  updatedAt: string | null
  createdAt: string | null
  isFork: boolean
  isArchived: boolean
  defaultBranch: string
  htmlUrl: string
}

export interface AccountMeta {
  login: string
  name: string | null
  bio: string | null
  avatarUrl: string | null
  type: 'User' | 'Organization'
  followers: number
  following: number
  publicRepos: number
  htmlUrl: string
  createdAt: string | null
}

/** Derived, normalized 0..1 visualization scores for one repo. */
export interface RepoScores {
  /** height_score = 0.6 * n(stars) + 0.4 * n(forks) */
  height: number
  /** glow_score = 0.5 * n(recent_push) + 0.3 * n(frequency proxy) + 0.2 * recency decay */
  glow: number
  /** footprint_score = 0.5 * n(size) + 0.25 * n(watchers) + 0.25 * n(stars) */
  footprint: number
  /** busyness_score = 0.4 * recency + 0.3 * n(watchers) + 0.3 * n(open issues) */
  busyness: number
  /** overall importance used for parcel placement (center = most important) */
  importance: number
  /** integer rank, 1 = most important */
  rank: number
}

export interface CityRepo {
  meta: RepoMeta
  scores: RepoScores
  /** world-space parcel center */
  x: number
  z: number
  /** derived world-space dimensions */
  heightUnits: number
  widthUnits: number
  depthUnits: number
  /** neon accent from primary language */
  accentColor: string
}

export interface CityModel {
  account: AccountMeta
  repos: CityRepo[]
  /** grid extents in world units, for ground/streets */
  halfExtent: number
  totals: {
    stars: number
    forks: number
    watchers: number
    openIssues: number
    languages: { language: string; count: number }[]
    recentlyActive: number
  }
}

export type CameraMode = 'orbit' | 'street' | 'cinematic'

export interface Filters {
  language: string | null
  query: string
  sortBy: 'importance' | 'stars' | 'forks' | 'activity' | 'name'
}
