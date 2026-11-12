import { expect, test } from 'claude-code/testing'

import { ago, footer, isBoss, laneRow, mailContext, needsProof, nextStep, prDetails, stack, workerDetails } from '../hooks/details'
import type { Pr, StageEvent, Worker } from '../types'

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
  expect(rows[0]?.color).toBe('success')
  expect(rows[0]?.value).toBe('1 pass · 1 fail (Ownership approval)')
})

const mk = (num: number, head: string, base: string, draft = false): Pr =>
  ({ repo: 'acme/widgets', primary: true, num, title: '', draft, review: '', merge: '', ci: 'green', reviewers: [], url: '', base, head, updated: '', proof: [] })

test('stacked PRs sit under their base, open roots before drafts', () => {
  const prs = [mk(3, 'c', 'b'), mk(9, 'z', 'main', true), mk(1, 'a', 'main'), mk(2, 'b', 'a')]
  expect(stack(prs).map(([p, depth]) => `${p.num}:${depth}`)).toEqual(['1:0', '2:1', '3:2', '9:0'])
})

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

test('each lane row says whose move it is', () => {
  const now = 10_000
  const row = (o: Partial<Worker>) => {
    const r = laneRow({ ...worker, ...o }, now)
    return `${r.mark} ${r.tag} ${r.parts.filter(p => p.text).map(p => p.text).join(' · ')}`
  }
  const proof = [{ label: 'page', url: 'https://example.com/p' }]
  expect(row({ stage: 'move', prTag: '#57', pr: pr({ review: 'APPROVED', proof }) })).toBe('› #57 approved + green · say merge')
  expect(row({ stage: 'move', prTag: '#57', pr: pr({ review: 'APPROVED' }) })).toBe('› #57 approved + green · no proof')
  expect(row({ stage: 'checking', prTag: '#61', events: [ev('9:58', now - 120, 'DONE')] })).toBe('◐ #61 DONE 2m ago · verifying')
  expect(row({ stage: 'checking', prTag: '#61', pr: pr({ ci: 'red' }) })).toBe('◐ #61 CI red · checking')
  expect(row({ stage: 'working', since: now - 360, events: [ev('', now - 360, 'sent', 'make test-http')] })).toBe('● restack-42 6m · make test-http')
  expect(row({ stage: 'working', state: 'blocked', since: now - 60, events: [ev('', now - 60, 'BLOCKED', 'needs a token')] })).toBe('■ restack-42 blocked: needs a token · 60s')
  const idle = laneRow({ ...worker, stage: 'working', state: 'idle', since: now - 600 }, now)
  expect([idle.dim, idle.parts[0]]).toEqual([true, { text: 'idle 10m', color: 'warning' }])
  expect(row({ stage: 'review', prTag: '#55', since: now - 86_400, pr: pr({ reviewers: ['JaneDoe42'] }) })).toBe('· #55 waiting on jane · 24h')
  expect(row({ stage: 'done', prTag: '#52', events: [ev('10:41', 1, 'merged'), ev('10:50', 2, 'retired')] })).toBe('✓ #52 merged 10:41 · retired')
  expect(row({ stage: 'done', events: [ev('11:02', 2, 'retired')] })).toBe('✓ restack-42 retired 11:02')
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
