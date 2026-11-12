/** A proof link: a published page, an artifact or a demo video. */
export type ProofLink = { label: string; url: string }
/** One line of a workspace's stage log (events.jsonl), with its local time. */
export type StageEvent = { at: number; ws: string; stage: string; note: string; hm: string }
/** Whose move a workspace is on: the lane it shows in. */
export type Stage = 'move' | 'checking' | 'working' | 'review' | 'done'
export type Worker = {
  ws: string
  id: string
  term: string
  name: string
  branch: string
  /** the task id, the ledger cell's first token */
  task: string
  /** the ledger's whole task cell, for the details */
  taskText?: string
  ledger: string
  date: string
  state: string
  watched: boolean
  proof: ProofLink[]
  stage: Stage
  /** when the current stage began (epoch s): its newest event, else its PR's update, else its ledger date */
  since: number
  /** its open PR, joined by branch */
  pr?: Pr | null
  /** that PR's tag ("#57", "ws#7"), remembered after it merges */
  prTag?: string
  /** its newest stage events, oldest first */
  events?: StageEvent[]
}
export type Watcher = { ws: string; term: string; ageS: number; stale: boolean }
export type Pr = {
  /** owner/repo */
  repo: string
  /** short repo tag for other repos' PRs: config's repo_aliases, else the repo name's initials */
  tag?: string
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
  proof: ProofLink[]
  /** when a comment starting a DONE envelope last landed (epoch s), 0 if never */
  doneAt?: number
  /** the workspace prefix this PR's branch belongs to; such PRs show in the lanes, not under PULL REQUESTS */
  ws?: string
}
export type Attention = { level: 'act' | 'check'; text: string }
/** One expanded row's details: label, value, and an optional theme color. */
export type Detail = { label: string; value: string; color?: string }
export type Peek = { key: string; rows: Detail[]; url?: string; links?: ProofLink[] }
export type Board = { mine?: number; p1?: number; inProgress?: number }
/** Another live boss, from the registry. */
export type OtherBoss = { id: string; project: string; workspace: string; working: number; forYou: number }
export type MailItem = { id: string; kind: string; from: string; subject: string }
export type Deck = {
  at: number
  me?: { id: string; project: string }
  others?: OtherBoss[]
  mail?: { count: number; dir: string; items: MailItem[] }
  lessonsNew?: number
  next: string
  review?: { url: string; date: string } | null
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
