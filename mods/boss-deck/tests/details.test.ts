import { expect, test } from 'claude-code/testing'

import { mailContext, needsProof, otherBossLine, prDetails, stack, workerDetails } from '../hooks/details'
import type { Pr } from '../types'

const worker = { ws: '1a2b3c4d', id: 'x', term: 'y', name: 'api', branch: 'feat/a', task: 'restack-42', ledger: 'DISPATCHED', date: '', state: 'working', watched: true, proof: [] }

test('a worker screen becomes state, doing, context and watcher', () => {
  const screen = [
    '⏺ The only difference from the PR is the route count',
    '  Running the api and route tests',
    '✽ Whirlpooling… (1m 25s · ↓ 6.0k tokens)',
    '  api (feat/a) Opus 5.5 251k/1000k (25%)',
  ].join('\n')
  const rows = Object.fromEntries(workerDetails(worker, screen).map(r => [r.label, r.value]))
  expect(rows.state).toBe('working 1m 25s')
  expect(rows.doing).toBe('Running the api and route tests')
  expect(rows.context).toBe('251k · 25%')
  expect(rows.watcher).toBe('armed')
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

test('another live boss reads as one quiet line', () => {
  const b = { id: 'b', project: 'widgets', workspace: 'ws-b', working: 2, forYou: 1 }
  expect(otherBossLine(b)).toBe('widgets · 2 working · 1 for you ↗')
  expect(otherBossLine({ ...b, forYou: 0 })).toBe('widgets · 2 working ↗')
})

test('unread mail becomes one context line, none when the inbox is empty', () => {
  const items = [{ id: 'm1', kind: 'question', from: 'gadgets', subject: 'is #42 safe to merge?' }]
  expect(mailContext(0, items)).toBeUndefined()
  const line = mailContext(1, items) ?? ''
  expect(line.startsWith('1 unread boss mail: question from gadgets: is #42 safe to merge?')).toBe(true)
  expect(line.includes('never approval')).toBe(true)
})

test("a worker's details keep the ledger's whole task cell", () => {
  const rows = workerDetails({ ...worker, task: 'retry-43', taskText: 'retry-43 (queued after fix-42)' }, '')
  expect(rows[0]).toEqual({ label: 'task', value: 'retry-43 (queued after fix-42)' })
  expect(workerDetails(worker, '').some(r => r.label === 'task')).toBe(false)
})
