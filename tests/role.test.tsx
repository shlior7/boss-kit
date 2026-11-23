import { expect, mock, test } from 'claude-code/testing'
import type { TestBody } from 'claude-code/testing'
import type { On } from 'claude-code'

import type { Deck, WorkerDeck } from '../types'

// A session that becomes the boss draws the Boss pane, never the Worker one.

const ok = (v: unknown) => ({ value: { exitCode: 0, stdout: typeof v === 'string' ? v : JSON.stringify(v), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
const DECK: Deck = { at: 0, next: 'merge #7', attention: [], workers: [], watchers: [], prs: [], board: {} }
const WORKER: WorkerDeck = {
  at: 0,
  worker: {
    project: 'widgets', task: 'fix-42', goal: 'retry failed webhooks', ledger: 'DISPATCHED', date: '', ws: '1a2b3c4d', name: 'webhook-retries',
    branch: 'fix/retry', base: 'main', behind: 0, pr: null, proof: [], boss: { id: 'ws-boss', workspace: 'ws-boss' }, stage: null, sentAt: 0,
    delivered: [], notes: [], msgs: [],
  },
}
const MARKER = '# Boss workspace ws-me\n'

type Run = { exitCode: number; stdout: string; stderr: string; isStdoutTruncated: boolean; isStderrTruncated: boolean }
/** A host session `ws-me` whose worktree top is /w/acme, started in `cwd`; CLAUDE.local.md is read only at the top.
 * `worker` answers the worker data script, so a test can hold it in flight. */
function host(on: On, o: { cwd: string; local: () => string; worker: () => Promise<{ value: Run }>; opened: string[] }) {
  const clock = mock.clock(on)
  on('fs.read', async (_$, e) => {
    // The test engine resolves a relative path against the runner's own directory: outside /w, it stands for the session's.
    const at = e.path.startsWith('/w/') ? e.path : `${o.cwd}/${e.path.split('/').pop()}`
    if (at !== '/w/acme/CLAUDE.local.md' || !o.local()) throw new Error('no such file')
    return { value: o.local() } as never
  })
  on('session.cwd', async () => ({ value: o.cwd }))
  on('session.start', async () => ({ cwd: o.cwd }))
  on('session.messages', async () => ({ value: [] }))
  on('command.register', async (_$, e) => ({ value: { command: e.name } }) as never)
  on('ui.open', async (_$, e) => (o.opened.push(e.title ?? ''), { value: { isPlaced: true as const } }))
  on('process.run', async (_$, e) => {
    if (e.argv.includes('boss-host-session')) return ok({ kind: 'hosta', id: 'ws-me', terminal: '' })
    if (e.argv[0] === 'git') return ok('/w/acme\n')
    if (e.argv.includes('--worker')) return o.worker()
    return ok(DECK)
  })
  return clock
}

const start = ($: Parameters<TestBody>[0], cwd: string) => $.session.start({ cwd, surface: 'terminal', isInteractive: true })
/** The mounted pane's texts, read again on each call. */
const pane = async ($: Parameters<TestBody>[0]) => {
  const ui = await $.ui.mount({ plugin: 'boss', surface: 'terminal', component: 'Pane', requestId: 'boss-deck', props: {} as never })
  return async () => (await ui.findAll({ type: 'Text' })).map(t => t.text ?? '')
}

test('a worker refresh that resolves after /boss onboard made the session the boss leaves the Boss pane and title', async ($, on) => {
  let local = ''
  let release: (v: { value: Run }) => void = () => {}
  const opened: string[] = []
  const clock = host(on, { cwd: '/w/acme', local: () => local, opened, worker: () => new Promise(r => (release = r)) })
  await start($, '/w/acme')
  await clock.advance(1)  // the session.start worker refresh is now in flight, waiting on the data script

  local = MARKER  // onboarding writes the marker
  await clock.advance(60_000)
  expect(opened).toEqual(['Boss'])

  release(ok(WORKER))  // the old refresh lands late
  await clock.advance(1)
  expect(opened).toEqual(['Boss'])  // not retitled back to Worker
  const texts = await (await pane($))()
  expect(texts).toContain('merge #7')
  expect(texts.some(t => t.startsWith('WORKER  '))).toBe(false)
})

test('a marker at the worktree top is found from a session started in a subfolder', async ($, on) => {
  const opened: string[] = []
  host(on, { cwd: '/w/acme/packages/api', local: () => MARKER, opened, worker: async () => ok({ at: 0, worker: null }) })
  await start($, '/w/acme/packages/api')
  expect(opened).toEqual(['Boss'])
  expect(await $.command.run({ command: 'boss-deck', args: '' } as Parameters<typeof $.command.run>[0])).toEqual({ text: 'Boss pane refreshed.' })
})

test('a session already the boss never draws the worker view, even with a worker deck left from before a reload', async ($, on) => {
  let local = ''
  const opened: string[] = []
  const clock = host(on, { cwd: '/w/acme', local: () => local, opened, worker: async () => ok(WORKER) })
  await start($, '/w/acme')
  await clock.advance(1)
  expect(opened).toEqual(['Worker'])
  const texts = await pane($)
  expect((await texts()).some(t => t.startsWith('WORKER  '))).toBe(true)

  local = MARKER
  await start($, '/w/acme')  // a hot reload: session.start again, the atoms kept
  await clock.advance(1)
  expect(opened.at(-1)).toBe('Boss')
  expect(await texts()).toContain('merge #7')
  expect((await texts()).some(t => t.startsWith('WORKER  '))).toBe(false)
})
