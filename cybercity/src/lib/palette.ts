/**
 * Cyber city visual language — night indigo world, neon accents.
 * Language → neon accent mapping (falls back to hash-picked neon).
 */
export const THEME = {
  sky: '#07040f',
  fog: '#0d0821',
  ground: '#080512',
  block: '#0e0a1e',
  sidewalk: '#151030',
  street: '#05030c',
  streetLine: '#2a1f5e',
  buildingBody: '#0b0819',
  neonPurple: '#a855f7',
  neonCyan: '#22d3ee',
  neonMagenta: '#e879f9',
  neonOrange: '#fb923c',
  neonGreen: '#34d399',
  hudCyan: '#67e8f9',
  textDim: '#8b84b8',
}

const LANGUAGE_COLORS: Record<string, string> = {
  TypeScript: '#38bdf8',
  JavaScript: '#facc15',
  Python: '#34d399',
  Rust: '#fb923c',
  Go: '#22d3ee',
  Java: '#f87171',
  'C++': '#e879f9',
  C: '#a5b4fc',
  'C#': '#a78bfa',
  Ruby: '#fb7185',
  PHP: '#818cf8',
  Swift: '#fbbf24',
  Kotlin: '#c084fc',
  Dart: '#2dd4bf',
  HTML: '#fb923c',
  CSS: '#60a5fa',
  Shell: '#4ade80',
  Vue: '#34d399',
  Svelte: '#fb7185',
  Elixir: '#c084fc',
  Haskell: '#a78bfa',
  Scala: '#f87171',
  Lua: '#60a5fa',
  R: '#93c5fd',
  Julia: '#c084fc',
  Zig: '#fbbf24',
  Jupyter: '#fb923c',
  'Jupyter Notebook': '#fb923c',
  Dockerfile: '#38bdf8',
  Makefile: '#a3a3a3',
}

const NEON_FALLBACKS = ['#a855f7', '#22d3ee', '#e879f9', '#34d399', '#fb923c', '#60a5fa', '#f472b6']

export function languageColor(language: string | null): string {
  if (language && LANGUAGE_COLORS[language]) return LANGUAGE_COLORS[language]
  if (!language) return THEME.neonPurple
  let h = 0
  for (let i = 0; i < language.length; i++) h = (h * 31 + language.charCodeAt(i)) >>> 0
  return NEON_FALLBACKS[h % NEON_FALLBACKS.length]
}
