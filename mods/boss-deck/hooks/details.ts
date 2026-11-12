import type { Deck, Detail, MailItem, OtherBoss, Pr, Worker } from '../types'

const ago = (s: number) => (s < 90 ? `${s}s` : s < 5400 ? `${Math.round(s / 60)}m` : `${Math.round(s / 3600)}h`)
const who = (login: string) => (login.includes('-') ? 'team' : (login.match(/^[A-Z]?[a-z]+/)?.[0] ?? login).toLowerCase())
const ACTIVITY = /^\s*(?:⏺\s+|⎿?\s*)?((?:Running|Ran|Reading|Read|Editing|Edited|Writing|Wrote|Searching|Fetching|Fixing|Merging|Pushing|Checking|Waiting)\b.*)$/
const SAID = /^\s*⏺\s+(?!Background command)(.{12,})$/
const SPINNER = /^\s*[✻✽✢✳·*]\s+\S+…\s+\((\d+m \d+s|\d+s|\d+h \d+m)/
const CTX = /(\d+)k\/1000k \((\d+)%\)/

/** A worker's screen as a few facts: what it is doing, for how long, how full, its last result. */
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
  const said = last(SAID)?.[1] ?? ''
  const spin = last(SPINNER)?.[1]
  const ctx = last(CTX)
  const env = screen.lastIndexOf('SUPERSET_WORKER_')
  const envelope =
    env < 0
      ? ''
      : (() => {
          const block = screen.slice(env, env + 1200).split('\n')
          const kind = block[0]?.includes('DONE') ? 'done' : 'blocked'
          const task = block.find(l => l.trim().startsWith('task:'))?.split(':')[1]?.trim() ?? ''
          const summary = block.find(l => /^\s*(summary|reason):/.test(l))?.replace(/^\s*(summary|reason):\s*/, '') ?? ''
          return `${kind} ${task}: ${summary}`
        })()
  const rows: Detail[] = [
    { label: 'state', value: w.state === 'working' && spin ? `working ${spin}` : w.state, color: w.state === 'blocked' ? 'error' : undefined },
    { label: 'branch', value: w.branch || '—' },
  ]
  if (w.taskText && w.taskText !== w.task) rows.unshift({ label: 'task', value: w.taskText })
  if (doing) rows.push({ label: 'doing', value: doing })
  if (said && said !== doing) rows.push({ label: 'said', value: said })
  if (envelope) rows.push({ label: 'last', value: envelope, color: envelope.startsWith('blocked') ? 'error' : undefined })
  if (ctx) {
    const pct = Number(ctx[2])
    rows.push({ label: 'context', value: `${ctx[1]}k · ${pct}%${pct >= 60 ? ' · clear soon' : ''}`, color: pct >= 60 ? 'warning' : undefined })
  }
  rows.push({ label: 'watcher', value: w.watched ? 'armed' : 'none', color: !w.watched && w.ledger === 'DISPATCHED' ? 'warning' : undefined })
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

/** One line per other live boss, "<project> · N working · M for you ↗", split so "M for you" can be colored. */
export function otherBossLine(b: OtherBoss): { quiet: string; forYou: string } {
  return { quiet: `${b.project} · ${b.working} working`, forYou: b.forYou ? ` · ${b.forYou} for you` : '' }
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
