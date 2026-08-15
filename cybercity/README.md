# GitHub Cyber City

Your GitHub footprint as a living, navigable cyberpunk metropolis — every
repository is a glowing tower on a street grid, and the account's identity and
stats float in a neon HUD.

This is a **visual identity and activity showcase built from repository
metadata only**. It is not a code intelligence tool: source code is never
read, fetched, summarized, or analyzed.

## Run it

```bash
cd cybercity
npm install
npm run dev        # http://localhost:5173
```

- Enter any public GitHub username or organization to generate its city, or
  click **"explore the demo city"** for instant mock data.
- Shareable URLs: `?user=<login>` (or `?demo`) generates a city on load, so a
  city can be linked publicly. The **⧉ SHARE CITY** button copies that link.
- An optional personal access token raises GitHub rate limits (60 → 5000
  req/hr). It is kept in memory only and sent only to `api.github.com`.

## Data rules

Only high-level metadata from the GitHub REST listing endpoints is used:

| Endpoint | Fields used |
|---|---|
| `GET /users/{login}` / `GET /orgs/{login}` | login, name, bio, avatar, type, followers, public repo count |
| `GET /users/{login}/repos` / `GET /orgs/{login}/repos` | name, description, stars, forks, watchers, open issues, primary language, size (KB), pushed_at / updated_at / created_at, fork & archived flags, default branch |
| `GET /repos/{o}/{r}/stats/participation` | 52 weekly commit **counts** for the default branch (numbers only — no messages, authors, or diffs) |

No contents, trees, blobs, or code-search endpoints are ever called
(`src/lib/github.ts` is the single API surface).

## Visualization scoring model

All raw metrics are log-normalized across the account so one giant repo does
not flatten the rest of the city:

```
n(x) = log10(1 + x) / log10(1 + max_x_across_repos)
```

| Score | Formula | Drives |
|---|---|---|
| **height** | `0.60·n(stars) + 0.40·n(forks)` | tower height (7–66 units) |
| **glow** (synced) | `0.50·n(c30) + 0.30·n(c90) + 0.20·recency` | window/trim/roof emissive intensity, point lights |
| **glow** (fallback) | `0.50·recent_push + 0.30·frequency + 0.20·recency` | same, from timestamps only |
| **footprint** | `0.50·n(size_kb) + 0.25·n(watchers) + 0.25·n(stars)` | building base dimensions |
| **busyness** (synced) | `0.40·n(c30) + 0.30·n(watchers) + 0.30·n(open_issues)` | lit-window density, drone & light-trail density |
| **busyness** (fallback) | `0.40·recency + 0.30·n(watchers) + 0.30·n(open_issues)` | same |
| **importance** | `0.45·height + 0.30·footprint + 0.25·glow` | parcel placement rank |

Activity terms are derived from timestamps only:

- `recency = exp(-days_since_push / 30)`
- `recent_push = 1 (≤7d) · 0.6 (≤30d) · 0.25 (≤90d) · ~0 beyond`
- `frequency = exp(-days_since_update / 60)`

See `src/lib/scoring.ts` — every formula is documented at the definition.

### Real commit windows (`src/lib/activity.ts`)

After the city first renders from listing metadata, the app enriches the top
30 repos by importance with **real commit-activity windows** in the
background — `c7` / `c30` / `c90` = commits in the last 1 / 4 / 13 weeks from
the participation endpoint. The HUD shows a "SYNCING COMMIT TRAFFIC n/m"
indicator, then the city re-scores so glow and busyness reflect actual commit
traffic. Rate-limit strategy: 6-hour localStorage cache per repo, concurrency
of 5, brief retries while GitHub computes stats (HTTP 202), and any 403/429
aborts the remainder — repos without synced windows keep the timestamp-proxy
formulas. Synced data also powers the account-wide COMMIT PULSE sparkline,
per-repo 7d/30d/90d stats, and real weekly bars on the hanging panels.

## City layout

- Square parcel grid: 26-unit lots + 12-unit streets (`src/lib/layout.ts`).
- Repos are placed in a **ring spiral from the center**, ordered by
  importance — rank 1 takes the center parcel and becomes the landmark tower
  carrying the account name on a floating neon sign.
- Each parcel gets a sidewalk apron and lot plate; streets carry animated
  commit-traffic light trails, and intersections have neon street lamps.
- A distant instanced skyline ring keeps the horizon alive, and a street-level
  marquee reads "EVERY COMMIT BUILDS THE FUTURE".

## The world

- **Buildings**: dark glass towers with procedurally lit window grids
  (density = busyness), neon edge trim in the primary language's color,
  tiered tops and beacon spires on tall towers, a holographic billboard
  (rank, name, ★, description, language chips) and a floating commit-traffic
  panel hanging off the side.
- **HUD (top-left)**: identity, repositories / followers / stars / forks /
  watchers / active-30d, language mix bar, recent-activity feed (click to fly
  to that building).
- **Top-right**: commit-traffic legend + system status.
- **Inspector**: click any building for full stats plus its four city-encoding
  scores, and a link to the repo on GitHub.
- **Controls**: search with fly-to suggestions, language filter (non-matching
  towers dim), orbit / street / cinematic camera modes, reset.
- **Ambience**: bloom + vignette, drones orbiting busy towers, animated light
  trails, starfield, fog.

## Stack

Vite · React 18 · TypeScript · three.js / React Three Fiber · drei ·
@react-three/postprocessing · zustand. No backend required for the MVP —
the city is generated client-side from public metadata.

## Roadmap

- GitHub OAuth (server-side) for one-click sign-in and private-repo *metadata*
  for the signed-in owner; background re-sync + persistence (Postgres) so
  cities update as accounts change.
- Contributor counts via additional metadata endpoints (rate-limit aware).
- First-person walk mode, org district grouping, timeline replay.
