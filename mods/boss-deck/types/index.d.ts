/** A proof link: a published page, an artifact or a demo video. */
export type ProofLink = { label: string; url: string }
/** One line of a workspace's stage log (events.jsonl), with its local time. */
export type StageEvent = { at: number; ws: string; stage: string; note: string; hm: string }
/** Whose move a workspace is on. */
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
  /** its Paradev tags (sidebar folders) */
  tags?: string[]
  /** its task progress, from <worktree>/.boss-worker/status.json, which its worker pane writes */
  tasks?: TaskProgress | null
  /** the last lines of <worktree>/.boss-worker/notes.md: its worker's decisions and open questions */
  notes?: string[]
}
export type TaskProgress = { done: number; total: number; current: string; at: number }
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
  /** the workspace prefix this PR's branch belongs to; a PR without one is its own row under WORKERS */
  ws?: string
}
export type Attention = { level: 'act' | 'check'; text: string }
/** One expanded row's details: label, value, and an optional theme color. */
export type Detail = { label: string; value: string; color?: string }
export type Peek = { key: string; rows: Detail[]; links?: ProofLink[] }
export type Board = { mine?: number; p1?: number; inProgress?: number }
/** Another live boss, from the registry. */
export type OtherBoss = { id: string; project: string; workspace: string; working: number; forYou: number }
/** One of this project's live bosses: the main boss ('' domain) or a domain boss, from its heartbeat. */
export type Boss = {
  id: string
  workspace: string
  domain: string
  /** this session's boss */
  me: boolean
  /** the first line of its next.txt */
  next: string
  working: number
  forYou: number
  /** its last heartbeat (epoch s), and whether that is older than a few refreshes */
  heartbeat: number
  stale: boolean
  /** the first lines of its domain state file; none for the main boss */
  state: string[]
}
export type MailItem = { id: string; kind: string; from: string; subject: string }
export type Deck = {
  at: number
  me?: { id: string; project: string }
  others?: OtherBoss[]
  bosses?: Boss[]
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

/** One DELIVERED line of a worker's view: a pushed commit ("commit") or a stage event (its stage). */
export type Delivered = { at: number; hm: string; kind: string; text: string }
/** A message the boss sent this workspace (a "msg" event). */
export type BossMsg = { at: number; hm: string; text: string }
/** A worker session's own view: its dispatch row, boss, PR, delivered work, notes and the boss's messages. */
export type WorkerView = {
  project: string
  task: string
  /** the ledger task cell without its id */
  goal: string
  ledger: string
  date: string
  ws: string
  name: string
  branch: string
  base: string
  /** commits origin/<base> has that HEAD lacks */
  behind: number
  pr: Pr | null
  proof: ProofLink[]
  boss: { id: string; workspace: string }
  /** its newest stage event other than a message */
  stage: StageEvent | null
  /** the last dispatch (epoch s), 0 if none logged */
  sentAt: number
  delivered: Delivered[]
  notes: string[]
  /** newest first */
  msgs: BossMsg[]
}
export type WorkerDeck = { at: number; worker: WorkerView | null; error?: string }
/** One item of the session's own task list (TodoWrite or the Task tools). */
export type Task = { id: string; subject: string; status: 'pending' | 'in_progress' | 'completed'; active?: string }
/** What the worker pane reads from its own session: whether a turn runs, when the last one began, the task list,
 * the latest activity and the context use. */
export type Live = { busy: boolean; turnAt: number; tasks: Task[]; now: string; ctx: number | null }

declare module 'claude-code' {
  interface PluginState {
    'boss-deck': { deck: Shaped<Deck | null>; peek: Shaped<Peek | null>; mine: Shaped<WorkerDeck | null>; live: Shaped<Live | null> }
  }
}
