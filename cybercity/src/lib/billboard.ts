/**
 * Canvas-texture generators for holographic billboards, window grids, and the
 * landmark name sign — matching the visual reference: dark glass panels with
 * neon type, rank number, star count, description, and language chips.
 */
import * as THREE from 'three'
import type { CityRepo } from './types'
import { THEME } from './palette'

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.arcTo(x + w, y, x + w, y + h, r)
  ctx.arcTo(x + w, y + h, x, y + h, r)
  ctx.arcTo(x, y + h, x, y, r)
  ctx.arcTo(x, y, x + w, y, r)
  ctx.closePath()
}

export function makeBillboardTexture(repo: CityRepo): THREE.CanvasTexture {
  const W = 512
  const H = 640
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')!
  const accent = repo.accentColor

  // dark glass panel
  ctx.fillStyle = 'rgba(8, 5, 24, 0.92)'
  roundRect(ctx, 6, 6, W - 12, H - 12, 22)
  ctx.fill()
  ctx.lineWidth = 5
  ctx.strokeStyle = accent
  ctx.shadowColor = accent
  ctx.shadowBlur = 24
  roundRect(ctx, 6, 6, W - 12, H - 12, 22)
  ctx.stroke()
  ctx.shadowBlur = 0

  const pad = 38
  let y = 96

  // rank
  ctx.fillStyle = THEME.hudCyan
  ctx.font = '600 40px "Courier New", monospace'
  ctx.fillText(String(repo.scores.rank).padStart(2, '0'), pad, y)
  y += 66

  // repo name (uppercase, wrapped if long)
  ctx.fillStyle = '#f5f3ff'
  ctx.shadowColor = accent
  ctx.shadowBlur = 18
  const name = repo.meta.name.toUpperCase()
  let nameSize = name.length > 14 ? 42 : 54
  ctx.font = `700 ${nameSize}px "Courier New", monospace`
  ctx.fillText(name.slice(0, 18), pad, y, W - pad * 2)
  ctx.shadowBlur = 0
  y += 64

  // stars
  ctx.fillStyle = '#fde68a'
  ctx.font = '600 38px "Courier New", monospace'
  ctx.fillText(`★ ${compact(repo.meta.stars)}`, pad, y)
  ctx.fillStyle = THEME.textDim
  ctx.fillText(`⎇ ${compact(repo.meta.forks)}`, pad + 190, y)
  y += 70

  // description, wrapped
  ctx.fillStyle = '#c4b5fd'
  ctx.font = '400 30px "Courier New", monospace'
  const desc = repo.meta.description ?? ''
  y = wrapText(ctx, desc, pad, y, W - pad * 2, 40, 4)
  y += 26

  // language chips
  const chips = [repo.meta.language ?? 'data'].concat(repo.meta.isArchived ? ['archived'] : [])
  let cx = pad
  ctx.font = '600 28px "Courier New", monospace'
  for (const chip of chips) {
    const tw = ctx.measureText(chip).width + 36
    ctx.fillStyle = 'rgba(34, 211, 238, 0.12)'
    roundRect(ctx, cx, H - 108, tw, 52, 12)
    ctx.fill()
    ctx.strokeStyle = accent
    ctx.lineWidth = 2
    roundRect(ctx, cx, H - 108, tw, 52, 12)
    ctx.stroke()
    ctx.fillStyle = accent
    ctx.fillText(chip, cx + 18, H - 72)
    cx += tw + 16
  }

  const tex = new THREE.CanvasTexture(canvas)
  tex.anisotropy = 4
  tex.colorSpace = THREE.SRGBColorSpace
  return tex
}

/** Hanging commit-traffic panel: pushed-at recency + activity pulse line. */
export function makeCommitPanelTexture(repo: CityRepo): THREE.CanvasTexture {
  const W = 512
  const H = 256
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')!
  const accent = repo.accentColor

  ctx.fillStyle = 'rgba(6, 4, 18, 0.9)'
  roundRect(ctx, 4, 4, W - 8, H - 8, 18)
  ctx.fill()
  ctx.strokeStyle = accent
  ctx.lineWidth = 4
  ctx.shadowColor = accent
  ctx.shadowBlur = 16
  roundRect(ctx, 4, 4, W - 8, H - 8, 18)
  ctx.stroke()
  ctx.shadowBlur = 0

  ctx.fillStyle = THEME.hudCyan
  ctx.font = '600 30px "Courier New", monospace'
  ctx.fillText('COMMIT TRAFFIC', 32, 56)

  const days = repo.meta.pushedAt ? Math.round((Date.now() - Date.parse(repo.meta.pushedAt)) / 86_400_000) : null
  ctx.fillStyle = '#f5f3ff'
  ctx.font = '400 30px "Courier New", monospace'
  ctx.fillText(days === null ? 'no data' : days <= 0 ? 'pushed today' : `pushed ${days}d ago`, 32, 104)

  // synthetic-but-deterministic activity pulse from glow/busyness
  ctx.strokeStyle = accent
  ctx.lineWidth = 3
  ctx.shadowColor = accent
  ctx.shadowBlur = 10
  ctx.beginPath()
  const amp = 14 + repo.scores.glow * 34
  for (let x = 0; x <= W - 64; x += 4) {
    const t = x / (W - 64)
    const yy = 176 - Math.sin(t * Math.PI * (2 + repo.scores.busyness * 6) + repo.meta.id) * amp * (0.4 + 0.6 * Math.sin(t * Math.PI))
    if (x === 0) ctx.moveTo(32 + x, yy)
    else ctx.lineTo(32 + x, yy)
  }
  ctx.stroke()
  ctx.shadowBlur = 0

  ctx.fillStyle = THEME.textDim
  ctx.font = '400 26px "Courier New", monospace'
  ctx.fillText(`issues ${repo.meta.openIssues} · watch ${repo.meta.watchers}`, 32, 232)

  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  return tex
}

/** Emissive window-grid texture; lit-window density follows busyness. */
export function makeWindowTexture(seed: number, busyness: number, accent: string): THREE.CanvasTexture {
  const W = 128
  const H = 256
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')!
  ctx.fillStyle = THEME.buildingBody
  ctx.fillRect(0, 0, W, H)

  let s = seed >>> 0
  const rnd = () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0
    return s / 0xffffffff
  }
  const cols = 10
  const rows = 26
  const cw = W / cols
  const ch = H / rows
  const litChance = 0.07 + busyness * 0.3
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const lit = rnd() < litChance
      if (!lit) {
        // unlit glass — near-black so the tower reads as a dark silhouette
        ctx.fillStyle = rnd() < 0.5 ? 'rgba(16, 12, 36, 0.9)' : 'rgba(22, 17, 48, 0.85)'
      } else {
        const warm = rnd() < 0.3
        ctx.globalAlpha = 0.5 + rnd() * 0.5
        ctx.fillStyle = warm ? '#ffd9a0' : accent
      }
      ctx.fillRect(c * cw + 3, r * ch + 3, cw - 6, ch - 6)
      ctx.globalAlpha = 1
    }
  }
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.wrapS = THREE.RepeatWrapping
  tex.wrapT = THREE.RepeatWrapping
  return tex
}

/** Landmark sign: the account name in big neon letters. */
export function makeNameSignTexture(text: string): THREE.CanvasTexture {
  const W = 1024
  const H = 256
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')!
  ctx.clearRect(0, 0, W, H)
  ctx.fillStyle = 'rgba(8, 5, 24, 0.75)'
  roundRect(ctx, 8, 8, W - 16, H - 16, 28)
  ctx.fill()
  ctx.strokeStyle = THEME.neonCyan
  ctx.lineWidth = 6
  ctx.shadowColor = THEME.neonCyan
  ctx.shadowBlur = 30
  roundRect(ctx, 8, 8, W - 16, H - 16, 28)
  ctx.stroke()

  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillStyle = '#f0fdff'
  ctx.shadowColor = THEME.neonMagenta
  ctx.shadowBlur = 34
  const t = text.toUpperCase()
  const size = Math.min(150, Math.floor((W - 120) / Math.max(1, t.length)) * 1.6)
  ctx.font = `700 ${size}px "Courier New", monospace`
  ctx.fillText(t, W / 2, H / 2 + 6)

  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  return tex
}

export function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

function wrapText(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  maxWidth: number,
  lineHeight: number,
  maxLines: number,
): number {
  const words = text.split(/\s+/).filter(Boolean)
  let line = ''
  let lines = 0
  for (const word of words) {
    const test = line ? `${line} ${word}` : word
    if (ctx.measureText(test).width > maxWidth && line) {
      ctx.fillText(line, x, y)
      y += lineHeight
      lines++
      line = word
      if (lines >= maxLines - 1) {
        line += '…'
        break
      }
    } else {
      line = test
    }
  }
  if (line) {
    ctx.fillText(line, x, y)
    y += lineHeight
  }
  return y
}
