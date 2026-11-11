import { expect, test } from 'claude-code/testing'

import { prDetails, stack, workerDetails } from '../hooks/details'
import type { Pr } from '../types'

const worker = { ws: '1a2b3c4d', id: 'x', term: 'y', name: 'api', branch: 'feat/a', task: 'restack-42', ledger: 'DISPATCHED', date: '', state: 'working', watched: true }

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
  const pr: Pr = { repo: 'acme/widgets', primary: true, num: 42, title: '', draft: false, review: '', merge: '', ci: 'green', reviewers: [], url: '', base: 'main', head: 'feat/b', updated: '' }
  const rows = prDetails(pr, { statusCheckRollup: [{ name: 'Ownership approval', conclusion: 'FAILURE' }, { name: 'build', conclusion: 'SUCCESS' }] }, 0)
  expect(rows[0]?.color).toBe('success')
  expect(rows[0]?.value).toBe('1 pass · 1 fail (Ownership approval)')
})

const mk = (num: number, head: string, base: string, draft = false): Pr =>
  ({ repo: 'acme/widgets', primary: true, num, title: '', draft, review: '', merge: '', ci: 'green', reviewers: [], url: '', base, head, updated: '' })

test('stacked PRs sit under their base, open roots before drafts', () => {
  const prs = [mk(3, 'c', 'b'), mk(9, 'z', 'main', true), mk(1, 'a', 'main'), mk(2, 'b', 'a')]
  expect(stack(prs).map(([p, depth]) => `${p.num}:${depth}`)).toEqual(['1:0', '2:1', '3:2', '9:0'])
})
