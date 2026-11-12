import { expect, mock, test } from 'claude-code/testing'

import type { Deck } from '../types'

const pr = { title: 'x', draft: false, review: '', merge: '', ci: 'green', reviewers: [], url: '', base: 'main', updated: '', proof: [] }
const PR57 = { ...pr, title: 'fix(login): rate-limit attempts', repo: 'acme/widgets', primary: true, num: 57, head: 'c', tag: 'w', ws: '5e6f7a8b', url: 'https://example.com/pr/57', proof: [{ label: 'page', url: 'https://example.com/page' }] } as Deck['prs'][0]
const DECK: Deck = {
  at: 0, next: '', attention: [], watchers: [], board: { mine: 2, p1: 1, inProgress: 1 },
  workers: [
    { ws: '1a2b3c4d', id: 'ws-1', term: 't', name: 'api', branch: 'b', task: 'retry-43', taskText: 'retry-43 (queued after fix-42)', ledger: 'QUEUED', date: '', state: 'working', watched: false, proof: [], stage: 'working', since: 0 },
    { ws: '5e6f7a8b', id: 'ws-2', term: 't', name: 'web-login', branch: 'c', task: 'fix-57', ledger: 'READY', date: '', state: 'idle', watched: false, proof: [{ label: 'page', url: 'https://example.com/page' }, { label: 'demo', url: 'https://example.com/run.mp4' }], stage: 'review', since: 0, prTag: '#57', pr: PR57 },
  ],
  prs: [
    { ...pr, repo: 'acme/widgets', primary: true, num: 7, head: 'a', tag: 'w' } as Deck['prs'][0],
    { ...pr, repo: 'acme/widgets-sdk', primary: false, num: 42, head: 'b', tag: 'ws' } as Deck['prs'][0],
    PR57,
  ],
  bosses: [
    { id: 'ws-me', workspace: 'ws-me', domain: '', me: true, next: '', working: 1, forYou: 0, heartbeat: 0, stale: false, state: [] },
    { id: 'ws-co', workspace: 'ws-co', domain: 'checkout', me: false, next: 'merge #61', working: 1, forYou: 2, heartbeat: 0, stale: false, state: [] },
  ],
  others: [{ id: 'ws-a', project: 'gadgets', workspace: 'ws-a', working: 1, forYou: 0 }],
  mail: { count: 1, dir: '/nonexistent', items: [{ id: 'm1', kind: 'question', from: 'gadgets', subject: 'is #42 safe?' }] },
}

test('the pane passes its workspace, and draws its inbox, its bosses, one WORKERS section and the board', async ($, on) => {
  const runs: string[][] = []
  mock.env(on, { SUPERSET_WORKSPACE_ID: 'ws-me' })
  mock.clock(on)
  on('session.cwd', async () => ({ value: '/w/boss' }))
  on('ui.open', async () => ({ value: { isPlaced: true as const } }))
  on('process.run', async (_$, e) => {
    runs.push([...e.argv])
    return { value: { exitCode: 0, stdout: JSON.stringify(DECK), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  // The engine stamps origin and presentation.
  await $.command.run({ command: 'boss-deck', args: '' } as Parameters<typeof $.command.run>[0])
  expect(runs[0]?.slice(-4)).toEqual(['--cwd', '/w/boss', '--workspace', 'ws-me'])

  const ui = await $.ui.mount({ plugin: 'boss-deck', surface: 'terminal', component: 'Pane', requestId: 'boss-deck', props: {} as never })
  const texts = (await ui.findAll({ type: 'Text' })).map(t => t.text)
  expect(texts).toContain('INBOX')
  expect(texts).toContain('gadgets: is #42 safe?')
  expect(texts.some(t => /gadgets · \d+ working/.test(t ?? ''))).toBe(false)  // other bosses are not listed
  const row = (start: string) => texts.find(t => (t ?? '').startsWith(start))?.replace(/ +/g, ' ')
  // exactly two sections between the inbox and the footer; the lanes and PULL REQUESTS are gone
  expect(texts.filter(t => /^[A-Z ]+$/.test(t ?? ''))).toEqual(['INBOX', 'BOSSES', 'WORKERS'])
  expect(texts).toContain('2 bosses')
  expect(row('main (this)')).toBe('main (this) 1 working · 0 for you')
  expect(row('checkout')).toBe('checkout 1 working · 2 for you')
  // active first, then idle, then the PRs no workspace owns; a joined PR is not repeated
  expect(texts).toContain('1 active · 3 idle')
  const order = texts.filter(t => /^(api|web-login|#7|ws#42) /.test(t ?? '')).map(t => t?.split(' ')[0])
  expect(order).toEqual(['api', 'web-login', '#7', 'ws#42'])
  expect(row('web-login')).toBe('web-login #57 in review · waiting on review')
  expect(row('ws#42')).toBe('ws#42 — open')
  expect(texts.some(t => (t ?? '').startsWith('#57'))).toBe(false)
  expect(texts.some(t => /queued after/.test(t ?? ''))).toBe(false)
  // its accordion: the workspace's history and next, the PR's rows, then one link row (the ledger's and the PR's proof,
  // deduplicated), arrow last on each
  await ui.press({ key: 'peek-w-5e6f7a8b' })
  const open = (await ui.findAll({ type: 'Text' })).map(t => t.text ?? '')
  const from = open.indexOf('next')
  expect(open.slice(from, from + 4)).toEqual(['next', 'reviewer: review #57', 'pr', 'rate-limit attempts'])
  expect(open.filter(t => t.endsWith('↗'))).toEqual(['page ↗', 'demo ↗', 'open workspace ↗', 'open on GitHub ↗'])
  expect(texts).toContain('tracker: 2 mine · 1 P0/P1 · 1 in progress')
})
