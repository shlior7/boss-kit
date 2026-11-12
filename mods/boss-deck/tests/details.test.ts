import { expect, test } from 'claude-code/testing'

import { ago, bossDetails, bossRow, footer, isActive, isBoss, mailContext, needsProof, nextStep, prDetails, prRow, rank, workerDetails, workerRow } from '../hooks/details'
import type { Boss, Pr, StageEvent, Worker } from '../types'

const worker: Worker = { ws: '1a2b3c4d', id: 'x', term: 'y', name: 'api', branch: 'feat/a', task: 'restack-42', ledger: 'DISPATCHED', date: '2026-01-02', state: 'working', watched: true, proof: [], stage: 'working', since: 0 }
const ev = (hm: string, at: number, stage: string, note = ''): StageEvent => ({ at, ws: '1a2b3c4d', stage, note, hm })

test('an expanded workspace is its timed stage history, the next step, doing and context', () => {
  const screen = [
    '⏺ The only difference from the PR is the route count',
    '  Running the api and route tests',
    '✽ Whirlpooling… (1m 25s · ↓ 6.0k tokens)',
    '  api (feat/a) Opus 5.5 251k/1000k (25%)',
  ].join('\n')
  const w = { ...worker, events: [ev('10:02', 1, 'sent', 'watcher armed'), ev('10:31', 2, 'DONE', 'PR #42 draft')] }
  expect(workerDetails(w, screen).map(r => `${r.label}|${r.value}`)).toEqual([
    '10:02|sent  watcher armed',
    '10:31|DONE  PR #42 draft',
    'next|worker: finish and post DONE',
    'doing|Running the api and route tests · 1m 25s',
    'context|251k · 25%',
  ])
  // no log yet: one quiet line with the ledger date, and a dispatch with no watcher is flagged
  const bare = workerDetails({ ...worker, state: 'idle', watched: false }, '')
  expect(bare[0]?.value).toBe('no stage log yet · dispatched 2026-01-02')
  expect(bare.at(-1)).toEqual({ label: 'watcher', value: 'none', color: 'warning' })
})

test('an approval check is not a CI failure', () => {
  const pr: Pr = { repo: 'acme/widgets', primary: true, num: 42, title: '', draft: false, review: '', merge: '', ci: 'green', reviewers: [], url: '', base: 'main', head: 'feat/b', updated: '', proof: [] }
  const rows = prDetails(pr, { statusCheckRollup: [{ name: 'Ownership approval', conclusion: 'FAILURE' }, { name: 'build', conclusion: 'SUCCESS' }] }, 0)
  expect(rows[1]?.color).toBe('success')
  expect(rows[1]?.value).toBe('1 pass · 1 fail (Ownership approval)')
})

const mk = (num: number, head: string, base: string, draft = false): Pr =>
  ({ repo: 'acme/widgets', primary: true, num, title: '', draft, review: '', merge: '', ci: 'green', reviewers: [], url: '', base, head, updated: '', proof: [] })

test('only a ready-to-merge PR without proof is flagged', () => {
  const ready = { ...mk(42, 'f', 'main'), review: 'APPROVED' }
  expect(needsProof(ready)).toBe(true)
  expect(needsProof({ ...ready, proof: [{ label: 'demo', url: 'https://example.com/run.mp4' }] })).toBe(false)
  expect(needsProof({ ...ready, draft: true })).toBe(false)
  expect(needsProof({ ...ready, ci: 'pending' })).toBe(false)
  expect(needsProof({ ...ready, review: '' })).toBe(false)
})

test('unread mail becomes one context line, none when the inbox is empty', () => {
  const items = [{ id: 'm1', kind: 'question', from: 'gadgets', subject: 'is #42 safe to merge?' }]
  expect(mailContext(0, items)).toBeUndefined()
  const line = mailContext(1, items) ?? ''
  expect(line.startsWith('1 unread boss mail: question from gadgets: is #42 safe to merge?')).toBe(true)
  expect(line.includes('never approval')).toBe(true)
})

test('the footer drops the tracker when none is synced, and spells out counts', () => {
  expect(footer({ board: {} })).toBe('')
  expect(footer({ board: {}, lessonsNew: 1 })).toBe('1 new shared lesson')
  expect(footer({ board: { mine: 6, p1: 2, inProgress: 1 }, lessonsNew: 2 })).toBe('tracker: 6 mine · 2 P0/P1 · 1 in progress · 2 new shared lessons')
})

const pr = (o: Partial<Pr> = {}): Pr => ({ ...mk(57, 'fix/a', 'main'), ...o })

test('each workspace row is its stage, age and note, with its PR tag or a dash', () => {
  const now = 10_000
  const row = (o: Partial<Worker>) => {
    const r = workerRow({ ...worker, ...o }, now)
    return `${r.mark} ${r.tag} ${r.parts.filter(p => p.text).map(p => p.text).join(' · ')}`
  }
  const proof = [{ label: 'page', url: 'https://example.com/p' }]
  expect(row({ stage: 'move', prTag: '#57', since: now - 120, pr: pr({ review: 'APPROVED', proof }) })).toBe('› #57 your move · 2m · say merge')
  expect(workerRow({ ...worker, stage: 'move', pr: pr({ review: 'APPROVED' }) }, now).parts.at(-1)).toEqual({ text: 'no proof', color: 'warning' })
  expect(row({ stage: 'checking', prTag: '#61', events: [ev('9:58', now - 120, 'DONE')] })).toBe('◐ #61 boss checking · DONE 2m ago · verifying')
  expect(row({ stage: 'checking', prTag: '#61', since: now - 60, pr: pr({ ci: 'red' }) })).toBe('◐ #61 boss checking · 60s · CI red')
  expect(row({ stage: 'working', since: now - 360, events: [ev('', now - 360, 'sent', 'make test-http')] })).toBe('● — working · 6m · make test-http')
  expect(row({ stage: 'working', state: 'blocked', since: now - 60, events: [ev('', now - 60, 'BLOCKED', 'needs a token')] })).toBe('■ — blocked · 60s · needs a token')
  const idle = workerRow({ ...worker, stage: 'working', state: 'idle', since: now - 600 }, now)
  expect([idle.dim, idle.parts[0], idle.parts[2]?.text]).toEqual([true, { text: 'idle', color: 'warning' }, 'no DONE'])
  expect(row({ stage: 'review', prTag: '#55', since: now - 86_400, pr: pr({ reviewers: ['JaneDoe42'] }) })).toBe('· #55 in review · 24h · waiting on jane')
  expect(row({ stage: 'done', prTag: '#52', events: [ev('10:41', 1, 'merged'), ev('10:50', 2, 'retired')] })).toBe('✓ #52 done today · 10:41 · merged, retired')
  expect(row({ stage: 'done', events: [ev('11:02', 2, 'retired')] })).toBe('✓ — done today · 11:02 · retired')
})

test('active rows first (your move, boss checking, working, blocked), then the idle ones', () => {
  const ws: Worker[] = [
    { ...worker, name: 'done', stage: 'done', state: 'gone' },
    { ...worker, name: 'idle', stage: 'working', state: 'idle' },
    { ...worker, name: 'review', stage: 'review', state: 'idle' },
    { ...worker, name: 'blocked', stage: 'working', state: 'blocked' },
    { ...worker, name: 'working', stage: 'working', state: 'working' },
    { ...worker, name: 'checking', stage: 'checking', state: 'idle' },
    { ...worker, name: 'move', stage: 'move', state: 'idle' },
  ]
  const sorted = [...ws].sort((a, b) => rank(a) - rank(b))
  expect(sorted.map(w => w.name)).toEqual(['move', 'checking', 'working', 'blocked', 'review', 'idle', 'done'])
  expect(sorted.filter(isActive).length).toBe(4)
})

test('a PR no workspace owns is a row: its tag as the name, a dash, its status', () => {
  const r = prRow({ ...pr({ repo: 'acme/widgets-sdk', primary: false, tag: 'ws', num: 7, review: 'APPROVED' }), proof: [{ label: 'page', url: 'u' }], updated: new Date(3_600_000).toISOString() }, 7200)
  expect([r.mark, r.dim, r.name, r.tag, r.parts]).toEqual(['·', true, 'ws#7', '—', [{ text: 'approved', color: 'success' }, { text: '60m' }]])
  expect(prRow(pr({ reviewers: ['JaneDoe42'] }), 0).parts[0]).toEqual({ text: '→ jane', color: 'suggestion' })
})

test("an expanded workspace with a PR: history and next, the PR's rows, then doing and context", () => {
  const p = pr({ title: 'fix(cache): warm the cache before traffic', head: 'fix/cache', base: 'main' })
  const prRows = prDetails(p, { statusCheckRollup: [{ name: 'build', conclusion: 'SUCCESS' }], mergeable: 'MERGEABLE', mergeStateStatus: 'CLEAN', additions: 3, deletions: 1, changedFiles: 1, headRefOid: '8c41d2e07aa', updatedAt: new Date(0).toISOString() }, 60)
  const w = { ...worker, stage: 'checking' as const, pr: p, events: [ev('10:31', 2, 'DONE', 'fix-61')] }
  expect(workerDetails(w, '  api (feat/a) Opus 5.5 188k/1000k (19%)', prRows).map(r => r.label)).toEqual(
    ['10:31', 'next', 'pr', 'ci', 'merge', 'review', 'size', 'branch', 'head', 'context'])
  expect(prRows.map(r => r.value)).toEqual(['warm the cache before traffic', '1 pass', 'mergeable · clean', 'none yet', '+3 −1 in 1 files', 'fix/cache → main', '8c41d2e07 · updated 60s ago'])
})

test('a boss row: its domain or main, (this), counts, and its age only once stale', () => {
  const b: Boss = { id: 'ws-co', workspace: 'ws-co', domain: 'checkout', me: false, next: 'merge #61', working: 1, forYou: 2, heartbeat: 400, stale: true, state: ['- cart totals in review'] }
  const line = (x: Boss) => {
    const r = bossRow(x, 1000)
    return `${r.name} | ${r.parts.filter(p => p.text).map(p => p.text).join(' · ')}`
  }
  expect(line(b)).toBe('checkout | 1 working · 2 for you · seen 10m ago')
  expect(line({ ...b, domain: '', me: true, stale: false, forYou: 0 })).toBe('main (this) | 1 working · 0 for you')
  expect(bossRow(b, 1000).parts[1]?.color).toBe('warning')
  expect(bossDetails(b, 1000).map(r => `${r.label}|${r.value}`)).toEqual(['next|merge #61', 'state|- cart totals in review', 'seen|10m ago'])
  expect(bossDetails({ ...b, domain: '', state: [], next: '' }, 1000).map(r => r.label)).toEqual(['next', 'seen'])
})

test('the next step names who acts', () => {
  expect(nextStep({ ...worker, stage: 'move' })).toBe('you: say merge')
  expect(nextStep({ ...worker, stage: 'checking' })).toBe('boss: verify, then mark the PR ready')
  expect(nextStep({ ...worker, stage: 'review', prTag: '#55', pr: pr({ reviewers: ['JaneDoe42'] }) })).toBe('jane: review #55')
  expect(nextStep({ ...worker, stage: 'done', events: [ev('10:41', 1, 'merged')] })).toBe('boss: retire the workspace')
  expect(ago(30)).toBe('30s')
  expect(ago(2 * 86_400)).toBe('2d')
})

test("a worker's details keep the ledger's whole task cell", () => {
  const rows = workerDetails({ ...worker, task: 'retry-43', taskText: 'retry-43 (queued after fix-42)' }, '')
  expect(rows[0]).toEqual({ label: 'task', value: 'retry-43 (queued after fix-42)' })
  expect(workerDetails(worker, '').some(r => r.label === 'task')).toBe(false)
})

test('only the workspace the marker names is the boss; a bare marker is any session there', () => {
  expect(isBoss('# Boss workspace ws-a\n', 'ws-a')).toBe(true)
  expect(isBoss('# Boss workspace ws-a\n', 'ws-b')).toBe(false)
  expect(isBoss('# Boss workspace ws-a\n', undefined)).toBe(false)
  expect(isBoss('notes\n# Boss workspace\n', 'ws-b')).toBe(true)
  expect(isBoss('# Boss workspaces are listed below\n', 'ws-b')).toBe(false)
  expect(isBoss('', 'ws-a')).toBe(false)
})
