export type Worker = {
  ws: string
  id: string
  term: string
  name: string
  branch: string
  task: string
  ledger: string
  date: string
  state: string
  watched: boolean
}
export type Watcher = { ws: string; term: string; ageS: number; stale: boolean }
export type Pr = {
  /** owner/repo */
  repo: string
  /** the project's own repo (its PRs show as plain #N) */
  primary: boolean
  num: number
  title: string
  draft: boolean
  review: string
  merge: string
  ci: 'green' | 'red' | 'pending'
  reviewers: string[]
  url: string
  base: string
  head: string
  updated: string
}
export type Attention = { level: 'act' | 'check'; text: string }
/** One expanded row's details: label, value, and an optional theme color. */
export type Detail = { label: string; value: string; color?: string }
export type Peek = { key: string; rows: Detail[]; url?: string }
export type Board = { mine?: number; p1?: number; inProgress?: number }
export type Deck = {
  at: number
  next: string
  attention: Attention[]
  workers: Worker[]
  watchers: Watcher[]
  prs: Pr[]
  board: Board
  error?: string
}

declare module 'claude-code' {
  interface PluginState {
    'boss-deck': { deck: Shaped<Deck | null>; peek: Shaped<Peek | null> }
  }
}
