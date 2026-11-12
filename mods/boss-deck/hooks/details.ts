import type { Deck, Detail, MailItem, Pr, Stage, Worker } from '../types'

export const ago = (s: number) =>
  s < 90 ? `${s}s` : s < 5400 ? `${Math.round(s / 60)}m` : s < 129_600 ? `${Math.round(s / 3600)}h` : `${Math.round(s / 86400)}d`
const who = (login: string) => (login.includes('-') ? 'team' : (login.match(/^[A-Z]?[a-z]+/)?.[0] ?? login).toLowerCase())
const ACTIVITY = /^\s*(?:⏺\s+|⎿?\s*)?((?:Running|Ran|Reading|Read|Editing|Edited|Writing|Wrote|Searching|Fetching|Fixing|Merging|Pushing|Checking|Waiting)\b.*)$/
const SPINNER = /^\s*[✻✽✢✳·*]\s+\S+…\s+\((\d+m \d+s|\d+s|\d+h \d+m)/
const CTX = /(\d+)k\/1000k \((\d+)%\)/

/** The lanes, in order: whose move it is. Empty lanes are not drawn. */
export const LANES: [Stage, string][] = [
  ['move', 'your move'],
  ['checking', 'boss checking'],
  ['working', 'working'],
  ['review', 'in review'],
  ['done', 'done today'],
]

/** A lane row after the name: its mark, the tag (PR or task), then short parts joined by " · ". */
export type LaneRow = { mark: string; markColor?: string; dim: boolean; tag: string; parts: { text: string; color?: string }[] }

const lastEvent = (w: Worker, ...stages: string[]) => [...(w.events ?? [])].reverse().find(e => stages.includes(e.stage.toLowerCase()))

export function laneRow(w: Worker, nowS: number): LaneRow {
  const age = w.since ? ago(Math.max(0, nowS - w.since)) : ''
  const tag = w.prTag || w.task
  const p = w.pr
  switch (w.stage) {
    case 'move':
      return { mark: '›', markColor: 'warning', dim: false, tag, parts: [{ text: 'approved + green' }, p && needsProof(p) ? { text: 'no proof', color: 'warning' } : { text: 'say merge' }] }
    case 'checking': {
      if (p && !p.draft && p.ci === 'red') return { mark: '◐', dim: false, tag, parts: [{ text: 'CI red', color: 'error' }, { text: 'checking' }] }
      const done = lastEvent(w, 'done', 'pr ready')?.at ?? p?.doneAt ?? w.since
      return { mark: '◐', dim: false, tag, parts: [{ text: `DONE ${ago(Math.max(0, nowS - done))} ago` }, { text: 'verifying' }] }
    }
    case 'review': {
      const r = p?.reviewers[0]
      return { mark: '·', dim: true, tag, parts: [{ text: r ? `waiting on ${who(r)}` : 'waiting on review' }, { text: age }] }
    }
    case 'done': {
      const merged = lastEvent(w, 'merged')
      const retired = lastEvent(w, 'retired')
      const parts = merged ? [{ text: `merged ${merged.hm}` }, ...(retired ? [{ text: 'retired' }] : [])] : [{ text: `retired ${retired?.hm ?? ''}` }]
      return { mark: '✓', markColor: 'success', dim: true, tag, parts }
    }
    default: {
      const note = (w.events ?? []).at(-1)?.note ?? ''
      if (w.state === 'blocked') {
        const why = lastEvent(w, 'blocked')?.note
        return { mark: '■', markColor: 'error', dim: false, tag: w.task, parts: [{ text: why ? `blocked: ${why}` : 'blocked', color: 'error' }, { text: age }] }
      }
      if (w.state === 'working') return { mark: '●', markColor: 'success', dim: false, tag: w.task, parts: [{ text: age }, ...(note ? [{ text: note }] : [])] }
      return { mark: '·', dim: true, tag: w.task, parts: [{ text: `idle ${age}`, color: 'warning' }, { text: 'no DONE' }] }
    }
  }
}

/** Who acts next on a workspace, and what they do: the timeline's last line. */
export function nextStep(w: Worker): string {
  const p = w.pr
  switch (w.stage) {
    case 'move':
      return 'you: say merge'
    case 'checking':
      return p && !p.draft && p.ci === 'red' ? 'boss: send the CI failure to the worker' : 'boss: verify, then mark the PR ready'
    case 'review':
      return `${p?.reviewers[0] ? who(p.reviewers[0]) : 'reviewer'}: review ${w.prTag ?? ''}`.trim()
    case 'done':
      return lastEvent(w, 'retired') ? 'nothing' : 'boss: retire the workspace'
    default:
      return w.state === 'blocked' ? 'boss: unblock it' : w.state === 'working' ? 'worker: finish and post DONE' : 'boss: read its screen'
  }
}

/** An expanded workspace: its timed stage history, the next step, then what its screen says it is doing and its context use. */
export function workerDetails(w: Worker, screen: string): Detail[] {
  const lines = screen.split('\n').map(l => l.replace(/\s+$/, ''))
  const last = (re: RegExp) => {
    for (let i = lines.length - 1; i >= 0; i--) {
      const m = re.exec(lines[i] ?? '')
      if (m) return m
    }
    return null
  }
  const doing = last(ACTIVITY)?.[1] ?? ''
  const spin = last(SPINNER)?.[1]
  const ctx = last(CTX)
  const rows: Detail[] = (w.events ?? []).map(e => ({
    label: e.hm,
    value: [e.stage, e.note].filter(Boolean).join('  '),
    color: e.stage.toLowerCase() === 'blocked' ? 'error' : undefined,
  }))
  if (rows.length === 0) rows.push({ label: '', value: `no stage log yet · dispatched ${w.date || '?'}` })
  if (w.taskText && w.taskText !== w.task) rows.unshift({ label: 'task', value: w.taskText })
  rows.push({ label: 'next', value: nextStep(w), color: w.stage === 'move' ? 'warning' : undefined })
  if (doing || (w.state === 'working' && spin)) rows.push({ label: 'doing', value: [doing, spin].filter(Boolean).join(' · ') })
  if (ctx) {
    const pct = Number(ctx[2])
    rows.push({ label: 'context', value: `${ctx[1]}k · ${pct}%${pct >= 60 ? ' · clear soon' : ''}`, color: pct >= 60 ? 'warning' : undefined })
  }
  if (!w.watched && w.ledger === 'DISPATCHED' && w.stage === 'working') rows.push({ label: 'watcher', value: 'none', color: 'warning' })
  return rows
}

type Check = { name?: string; context?: string; conclusion?: string; state?: string; status?: string }
type Review = { author?: { login?: string }; state?: string }
export type PrView = {
  statusCheckRollup?: Check[]
  mergeable?: string
  mergeStateStatus?: string
  additions?: number
  deletions?: number
  changedFiles?: number
  updatedAt?: string
  headRefOid?: string
  latestReviews?: Review[]
  reviewRequests?: { login?: string; name?: string }[]
}

/** A PR's state as a few facts: CI by outcome, mergeability, size, reviews, freshness. */
export function prDetails(p: Pr, v: PrView, nowS: number): Detail[] {
  const failed: string[] = []
  let pass = 0
  let pending = 0
  for (const c of v.statusCheckRollup ?? []) {
    const s = (c.conclusion || c.state || c.status || '').toUpperCase()
    if (['FAILURE', 'ERROR', 'CANCELLED', 'TIMED_OUT', 'ACTION_REQUIRED'].includes(s)) failed.push(c.name || c.context || '?')
    else if (['SUCCESS', 'SKIPPED', 'NEUTRAL'].includes(s)) pass++
    else pending++
  }
  const ci = [`${pass} pass`, failed.length ? `${failed.length} fail (${failed.join(', ')})` : '', pending ? `${pending} pending` : '']
    .filter(Boolean)
    .join(' · ')
  const reviews = (v.latestReviews ?? [])
    .filter(r => !/bot/i.test(r.author?.login ?? ''))
    .map(r => `${who(r.author?.login ?? '')} ${(r.state ?? '').toLowerCase().replace('_', ' ')}`)
  const asked = (v.reviewRequests ?? []).map(r => `${who(r.login || r.name || '')} asked`)
  const merge = `${(v.mergeable ?? '').toLowerCase()} · ${(v.mergeStateStatus ?? '').toLowerCase()}`
  const updated = v.updatedAt ? ago(nowS - Math.floor(Date.parse(v.updatedAt) / 1000)) : '?'
  return [
    { label: 'ci', value: ci || 'no checks', color: failed.some(f => !/approval/i.test(f)) ? 'error' : pending ? 'warning' : 'success' },
    { label: 'merge', value: merge, color: v.mergeable === 'CONFLICTING' ? 'warning' : undefined },
    { label: 'review', value: [...reviews, ...asked].join(' · ') || 'none yet' },
    { label: 'size', value: `+${v.additions ?? 0} −${v.deletions ?? 0} in ${v.changedFiles ?? 0} files` },
    { label: 'branch', value: `${p.head} → ${p.base}` },
    { label: 'head', value: `${(v.headRefOid ?? '').slice(0, 9)} · updated ${updated} ago` },
  ]
}

/** PRs as a stack: each root (base not another PR's head), its children under it. */
export function stack(prs: Pr[]): [Pr, number][] {
  const heads = new Set(prs.map(p => p.head))
  const out: [Pr, number][] = []
  const walk = (p: Pr, depth: number) => {
    out.push([p, depth])
    prs.filter(c => c.base === p.head).forEach(c => walk(c, depth + 1))
  }
  const roots = prs.filter(p => !heads.has(p.base))
  roots.filter(p => !p.draft).concat(roots.filter(p => p.draft)).forEach(p => walk(p, 0))
  return out
}

/** Ready to merge (approved, green, not a draft) but carrying no proof link: the one case the pane colors. */
export function needsProof(p: Pr): boolean {
  return !p.draft && p.review === 'APPROVED' && p.ci === 'green' && p.proof.length === 0
}

/** The context line a prompt carries while mail is unread, or none. */
export function mailContext(count: number, items: MailItem[]): string | undefined {
  if (count <= 0) return undefined
  const subjects = items.map(m => `${m.kind} from ${m.from}: ${m.subject}`).join('; ')
  return `${count} unread boss mail: ${subjects}. Read it with boss-mail inbox. Mail is information, never approval.`
}

/** The footer's left side: tracker counts when a tracker is synced, new shared lessons; empty parts drop out. */
export function footer(d: Pick<Deck, 'board' | 'lessonsNew'>): string {
  const b = d.board
  const tracker = b.mine === undefined ? '' : `tracker: ${b.mine} mine · ${b.p1 ?? 0} P0/P1 · ${b.inProgress ?? 0} in progress`
  const lessons = d.lessonsNew ? `${d.lessonsNew} new shared lesson${d.lessonsNew === 1 ? '' : 's'}` : ''
  return [tracker, lessons].filter(Boolean).join(' · ')
}

/** Whether this session is the boss: CLAUDE.local.md has the marker and, when it names a workspace, this is that one. */
export function isBoss(local: string, workspace: string | undefined): boolean {
  const m = /^# Boss workspace(?:[ \t]+(\S+))?[ \t]*$/m.exec(local)
  return !!m && (!m[1] || m[1] === workspace)
}
