import { expect, mock, test } from 'claude-code/testing'

import type { Deck } from '../types'

const pr = { title: 'x', draft: false, review: '', merge: '', ci: 'green', reviewers: [], url: '', base: 'main', updated: '', proof: [] }
const DECK: Deck = {
  at: 0, next: '', attention: [], watchers: [], board: { mine: 2, p1: 1, inProgress: 1 },
  workers: [{ ws: '1a2b3c4d', id: 'ws-1', term: 't', name: 'api', branch: 'b', task: 'retry-43', taskText: 'retry-43 (queued after fix-42)', ledger: 'QUEUED', date: '', state: 'idle', watched: false, proof: [] }],
  prs: [
    { ...pr, repo: 'acme/widgets', primary: true, num: 7, head: 'a', tag: 'w' } as Deck['prs'][0],
    { ...pr, repo: 'acme/widgets-sdk', primary: false, num: 42, head: 'b', tag: 'ws' } as Deck['prs'][0],
  ],
  others: [
    { id: 'ws-a', project: 'gadgets', workspace: 'ws-a', working: 1, forYou: 0 },
    { id: 'ws-b', project: 'gizmos', workspace: 'ws-b', working: 0, forYou: 0 },
  ],
}

test('the pane passes its workspace, and draws each other boss once, short repo tags, task ids and the board', async ($, on) => {
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
  expect(texts.filter(t => /working ↗$/.test(t ?? ''))).toEqual(['gadgets · 1 working ↗', 'gizmos · 0 working ↗'])
  expect(texts).toContain('#7')
  expect(texts).toContain('ws#42')
  expect(texts).toContain('retry-43')
  expect(texts.some(t => /queued after/.test(t ?? ''))).toBe(false)
  expect(texts).toContain('tracker: 2 mine · 1 P0/P1 · 1 in progress')
})
