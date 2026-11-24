import { expect, mock, test } from 'claude-code/testing'
import type { On, SessionMessage } from 'claude-code'

import { workerDetails } from '../hooks/details'
import { activity, newMsgs, progress, prParts, taskList, workerWarnings } from '../hooks/worker'
import type { Live, Pr, Worker, WorkerDeck, WorkerView } from '../types'

const use = (tool: string, input: Record<string, unknown>, result?: unknown) => ({ tool_use_id: `${tool}-${Math.random()}`, tool, input, result })
const said = (text: string, toolUses: ReturnType<typeof use>[] = []): SessionMessage => ({ role: 'assistant', text, toolUses })

test('the task list follows TodoWrite, and TaskCreate / TaskUpdate by id', () => {
  const todo = (content: string, status: string) => ({ content, status, activeForm: `${content}ing` })
  expect(taskList([said('', [use('TodoWrite', { todos: [todo('plan', 'completed'), todo('build', 'in_progress')] })])]).map(t => `${t.status} ${t.subject}`)).toEqual([
    'completed plan',
    'in_progress build',
  ])
  const msgs = [
    said('', [use('TaskCreate', { subject: 'write the queue', description: '' }, { task: { id: '7', subject: 'write the queue' } })]),
    said('', [use('TaskCreate', { subject: 'run the tests', description: '', activeForm: 'Running the tests' }, { task: { id: '8', subject: 'run the tests' } })]),
    said('', [use('TaskCreate', { subject: 'drop me', description: '' }, { task: { id: '9', subject: 'drop me' } })]),
    said('', [use('TaskUpdate', { taskId: '7', status: 'completed' }), use('TaskUpdate', { taskId: '8', status: 'in_progress' }), use('TaskUpdate', { taskId: '9', status: 'deleted' })]),
  ]
  const tasks = taskList(msgs)
  expect(tasks.map(t => `${t.id} ${t.status}`)).toEqual(['7 completed', '8 in_progress'])
  expect(progress(tasks)).toEqual({ tasks_done: 1, tasks_total: 2, current: 'Running the tests' })
  expect(progress([])).toEqual({ tasks_done: 0, tasks_total: 0, current: '' })
})

test('now is the latest tool call, else one line of the latest assistant text', () => {
  expect(activity([said('Reading the queue', [use('Bash', { command: 'make test-http\nmore' })]), { role: 'user', text: 'ok', toolUses: [] }])).toBe('Bash(make test-http)')
  expect(activity([said('', [use('Read', { file_path: 'a.py' })]), said('\n  Backoff caps at five retries.\nmore')])).toBe('Backoff caps at five retries.')
  expect(activity([])).toBe('')
})

const pr = (o: Partial<Pr> = {}): Pr => ({ repo: 'acme/widgets', primary: true, num: 61, title: '', draft: true, review: '', merge: 'MERGEABLE', ci: 'green', reviewers: [], url: 'https://example.com/pr/61', base: 'main', head: 'fix/retry', updated: '', proof: [], ...o })
const view = (o: Partial<WorkerView> = {}): WorkerView => ({
  project: 'widgets', task: 'fix-42', goal: 'retry failed webhooks with backoff', ledger: 'DISPATCHED', date: '2026-01-02', ws: '1a2b3c4d', name: 'webhook-retries',
  branch: 'fix/retry', base: 'main', behind: 0, pr: pr(), proof: [], boss: { id: 'ws-boss', workspace: 'ws-boss' }, stage: null, sentAt: 100,
  delivered: [], notes: [], msgs: [], ...o,
})
const lv = (o: Partial<Live> = {}): Live => ({ busy: true, turnAt: 0, tasks: [], now: '', ctx: 20, ...o })

test('warnings: context, behind its base, red CI, idle with no DONE comment', () => {
  expect(workerWarnings(view(), lv())).toEqual([])
  expect(workerWarnings(view(), lv(), true)).toEqual(['kit updated · restart: claude --continue'])
  expect(workerWarnings(view({ behind: 2, pr: pr({ ci: 'red' }) }), lv({ ctx: 64 }))).toEqual(['context 64% · clear soon', '2 behind origin/main', 'CI red'])
  expect(workerWarnings(view(), lv({ busy: false, turnAt: 5 }))).toEqual(['idle, no DONE comment on the PR'])
  expect(workerWarnings(view({ pr: pr({ doneAt: 200 }) }), lv({ busy: false, turnAt: 5 }))).toEqual([])
  expect(workerWarnings(view({ pr: pr({ doneAt: 50 }) }), lv({ busy: false, turnAt: 5 }))).toEqual(['idle, no DONE comment on the PR'])  // before this dispatch
  expect(workerWarnings(view({ pr: null }), lv({ busy: false, turnAt: 5 }))).toEqual([])
})

test('the PR row, and which boss messages are new since the last turn', () => {
  expect(prParts(pr()).map(p => p.text)).toEqual(['#61', 'draft', 'CI ✓', 'mergeable', 'no review'])
  expect(prParts(pr({ draft: false, ci: 'red', review: 'APPROVED' })).map(p => p.text)).toEqual(['#61', 'ready', 'CI ✗', 'mergeable', 'approved'])
  const msgs = [{ at: 300, hm: '', text: 'b' }, { at: 100, hm: '', text: 'a' }]
  expect(newMsgs(view({ msgs }), lv({ turnAt: 200_000 }))).toBe(1)
  expect(newMsgs(view({ msgs }), null)).toBe(2)
})

test("the boss's expanded row carries the worker's task progress and its notes", () => {
  const w: Worker = { ws: '1a2b3c4d', id: 'x', term: 'y', name: 'api', branch: 'b', task: 'fix-42', ledger: 'DISPATCHED', date: '', state: 'working', watched: true, proof: [], stage: 'working', since: 0,
    tasks: { done: 3, total: 5, current: 'Running the http tests', at: 0 }, notes: ['- decided: cap at 5', '- open: retry 4xx?'] }
  const rows = workerDetails(w, '').map(r => `${r.label}|${r.value}`)
  expect(rows.slice(rows.indexOf('next|worker: finish and post DONE') + 1)).toEqual(['tasks|3 of 5 · now Running the http tests', 'notes|- decided: cap at 5', '|- open: retry 4xx?'])
  expect(workerDetails({ ...w, tasks: { done: 0, total: 0, current: '', at: 0 } , notes: [] }, '').some(r => r.label === 'tasks')).toBe(false)
})

const WORKER: WorkerDeck = {
  at: 0,
  worker: view({
    stage: { at: 0, ws: '1a2b3c4d', stage: 'sent', note: '', hm: '10:02' },
    delivered: [{ at: 2, hm: '10:31', kind: 'commit', text: '8c41d2e add backoff' }, { at: 1, hm: '10:02', kind: 'sent', text: 'fix-42' }],
    behind: 2, notes: ['- open: retry 4xx?'], msgs: [{ at: 3, hm: '10:40', text: 'also cover 429' }],
    pr: pr({ proof: [{ label: 'page', url: 'https://example.com/page' }] }),
  }),
}

function session(on: On, deck: WorkerDeck | object, opened: string[], runs: string[][], sess: object = { kind: 'hosta', id: '1a2b3c4d-full', terminal: '' }, failedLookups = 0) {
  const clock = mock.clock(on)
  on('fs.read', async () => {
    throw new Error('no CLAUDE.local.md')
  })
  on('session.cwd', async () => ({ value: '/w/worker' }))
  on('session.start', async () => ({ cwd: '/w/worker' }))
  on('command.register', async (_$, e) => ({ value: { command: e.name } }) as never)
  on('session.messages', async () => ({
    value: [said('', [use('TaskCreate', { subject: 'write the queue', description: '' }, { task: { id: '1', subject: '' } }), use('TaskUpdate', { taskId: '1', status: 'completed' }),
      use('TaskCreate', { subject: 'run the tests', description: '', activeForm: 'Running the tests' }, { task: { id: '2', subject: '' } }), use('TaskUpdate', { taskId: '2', status: 'in_progress' }),
      use('TaskCreate', { subject: 'update the docs', description: '' }, { task: { id: '3', subject: '' } }), use('Bash', { command: 'make test-http' })])],
  }))
  on('ui.open', async (_$, e) => {
    opened.push(e.title ?? '')
    return { value: { isPlaced: true as const } }
  })
  on('process.run', async (_$, e) => {
    if (e.argv[0] === 'git') return { value: { exitCode: 128, stdout: '', stderr: 'not a git repository', isStdoutTruncated: false, isStderrTruncated: false } }
    if (e.argv.includes('boss-host-session')) {
      runs.push(['boss-host-session'])
      if (failedLookups-- > 0) return { value: { exitCode: 1, stdout: '', stderr: 'Traceback', isStdoutTruncated: false, isStderrTruncated: false } }
      return { value: { exitCode: 0, stdout: JSON.stringify(sess), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
    }
    runs.push([...e.argv])
    return { value: { exitCode: 0, stdout: JSON.stringify(deck), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  return clock
}

test('a failed host lookup is not outside a host: the pane asks again a minute later and starts then', async ($, on) => {
  const opened: string[] = []
  const runs: string[][] = []
  const clock = session(on, WORKER, opened, runs, undefined, 1)
  await $.session.start({ cwd: '/w/worker', surface: 'terminal', isInteractive: true })
  expect(runs).toEqual([['boss-host-session']])
  expect(opened).toEqual([])
  await clock.advance(60_000)
  expect(runs.filter(r => r[0] === 'boss-host-session').length).toBe(2)
  expect(runs.some(r => r.includes('--worker'))).toBe(true)
  expect(opened).toEqual(['Worker'])
})

test('no dispatch row for this workspace: no pane', async ($, on) => {
  const opened: string[] = []
  const runs: string[][] = []
  session(on, { at: 0, worker: null }, opened, runs)
  await $.session.start({ cwd: '/w/worker', surface: 'terminal', isInteractive: true })
  const said = await $.command.run({ command: 'boss-deck', args: '' } as Parameters<typeof $.command.run>[0])
  expect(runs.some(r => r.includes('--worker'))).toBe(true)
  expect(opened).toEqual([])
  expect(said).toEqual({ text: 'Not a boss here: run /boss to set one up. No boss ledger has a dispatch row for this workspace either.' })
})

test('a session on any host plugin is a worker too: its id and host go to the data script', async ($, on) => {
  const opened: string[] = []
  const runs: string[][] = []
  session(on, WORKER, opened, runs, { kind: 'hostb', id: 'aaaa1111', terminal: 'agent-1' })
  await $.session.start({ cwd: '/w/worker', surface: 'terminal', isInteractive: true })
  await $.command.run({ command: 'boss-deck', args: '' } as Parameters<typeof $.command.run>[0])
  const run = runs.find(r => r.includes('--worker')) ?? []
  expect(run.slice(-9, -4)).toEqual(['--host-kind', 'hostb', '--worker', '--workspace', 'aaaa1111'])
  expect(opened[0]).toBe('Worker')
})

test('a dispatched worker gets its own view, top to bottom', async ($, on) => {
  const opened: string[] = []
  const runs: string[][] = []
  session(on, WORKER, opened, runs)
  await $.session.start({ cwd: '/w/worker', surface: 'terminal', isInteractive: true })
  const said = await $.command.run({ command: 'boss-deck', args: '' } as Parameters<typeof $.command.run>[0])
  expect(said).toEqual({ text: 'Worker pane refreshed.' })
  const run = runs.find(r => r.includes('--worker')) ?? []
  expect(run.slice(-7)).toEqual(['--worker', '--workspace', '1a2b3c4d-full', '--cwd', '/w/worker', '--status', JSON.stringify({ tasks_done: 1, tasks_total: 3, current: 'Running the tests' })])
  expect(opened[0]).toBe('Worker')

  const ui = await $.ui.mount({ plugin: 'boss', surface: 'terminal', component: 'Pane', requestId: 'boss-deck', props: {} as never })
  const texts = (await ui.findAll({ type: 'Text' })).map(t => t.text ?? '')
  expect(texts.filter(t => /^[A-Z ]+$/.test(t))).toEqual(['TASKS', 'DELIVERED', 'NOTES', 'FROM BOSS'])
  expect(texts).toContain('WORKER  webhook-retries · fix-42')
  expect(texts).toContain('boss: widgets')
  expect(texts).toContain('retry failed webhooks with backoff')
  expect(texts.find(t => t.startsWith('#61'))).toBe('#61 · draft · CI ✓ · mergeable · no review')
  expect(texts.find(t => t.startsWith('idle') || t.startsWith('working'))).toMatch(/^idle · sent \d+\w ago · now: Bash\(make test-http\)$/)
  expect(texts).toContain('1 of 3 done')
  expect(texts.filter(t => /^[✓●○]$/.test(t))).toEqual(['✓', '●', '○'])
  expect(texts).toContain('Running the tests')
  expect(texts).toContain('8c41d2e add backoff')
  expect(texts).toContain('- open: retry 4xx?')
  expect(texts).toContain('1 new')
  expect(texts).toContain('! 2 behind origin/main')  // no turn seen yet: no idle warning; context % comes from the host
  expect(texts.filter(t => t.endsWith('↗'))).toEqual(['page ↗', 'PR ↗', 'boss ↗'])
  expect(texts.some(t => /^\d+s ago$/.test(t))).toBe(true)
})

test('a worker pane warns once the kit on disk moves past the one it loaded', async ($, on) => {
  const deck = { ...WORKER, kit: 'a1b2c3d' }
  session(on, deck, [], [])
  await $.session.start({ cwd: '/w/worker', surface: 'terminal', isInteractive: true })
  await $.command.run({ command: 'boss-deck', args: '' } as Parameters<typeof $.command.run>[0])
  const ui = await $.ui.mount({ plugin: 'boss', surface: 'terminal', component: 'Pane', requestId: 'boss-deck', props: {} as never })
  const warnings = async () => (await ui.findAll({ type: 'Text' })).map(t => t.text ?? '').filter(t => t.startsWith('!'))
  expect(await warnings()).toEqual(['! 2 behind origin/main'])
  deck.kit = 'e4f5a6b'
  await $.command.run({ command: 'boss-deck', args: '' } as Parameters<typeof $.command.run>[0])
  expect(await warnings()).toEqual(['! 2 behind origin/main · kit updated · restart: claude --continue'])
})

test('a worker view lists the pages it published, newest first, under the provider line', async ($, on) => {
  const pages = [{ url: 'https://example.com/after', title: 'after run', at: 0 }, { url: 'https://example.com/before', title: 'before run', at: 0 }]
  const deck: WorkerDeck = { at: 0, worker: view({ pagesTo: 'acme-pages', pages, proof: [{ label: 'page', url: 'https://example.com/after' }, { label: 'demo', url: 'https://example.com/run.mp4' }] }) }
  session(on, deck, [], [])
  await $.session.start({ cwd: '/w/worker', surface: 'terminal', isInteractive: true })
  await $.command.run({ command: 'boss-deck', args: '' } as Parameters<typeof $.command.run>[0])
  const ui = await $.ui.mount({ plugin: 'boss', surface: 'terminal', component: 'Pane', requestId: 'boss-deck', props: {} as never })
  const texts = (await ui.findAll({ type: 'Text' })).map(t => t.text ?? '')
  expect(texts).toContain('pages → acme-pages')
  expect(texts.filter(t => /^[A-Z ]+$/.test(t))).toContain('PAGES')
  expect(texts.filter(t => t.endsWith('↗'))).toEqual(['after run ↗', 'before run ↗', 'demo ↗', 'PR ↗', 'boss ↗'])  // a listed page is not repeated
})

test('a worker session onboarded as the boss mid-session becomes the boss on its next tick: one pane, one timer', async ($, on) => {
  let local = ''
  const opened: string[] = []
  const runs: string[][] = []
  const commands: string[] = []
  const clock = mock.clock(on)
  on('fs.read', async () => {
    if (!local) throw new Error('no CLAUDE.local.md')
    return { value: local } as never
  })
  on('session.cwd', async () => ({ value: '/w/boss' }))
  on('session.messages', async () => ({ value: [] }))
  on('session.start', async () => ({ cwd: '/w/boss' }))
  on('command.register', async (_$, e) => {
    commands.push(e.description ?? '')
    return { value: { command: e.name } } as never
  })
  on('ui.open', async (_$, e) => {
    opened.push(e.title ?? '')
    return { value: { isPlaced: true as const } }
  })
  on('process.run', async (_$, e) => {
    if (e.argv[0] === 'git') return { value: { exitCode: 128, stdout: '', stderr: 'not a git repository', isStdoutTruncated: false, isStderrTruncated: false } }
    const sess = e.argv.includes('boss-host-session')
    if (!sess) runs.push([...e.argv])
    const stdout = JSON.stringify(sess ? { kind: 'hosta', id: 'ws-me', terminal: '' } : { at: 0, worker: null })
    return { value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  await $.session.start({ cwd: '/w/boss', surface: 'terminal', isInteractive: true })
  await clock.advance(1)  // the first worker refresh runs unawaited
  expect(runs.length).toBe(1)
  expect(runs[0]).toContain('--worker')

  local = '# Boss workspace ws-me\n'  // /boss onboard writes the marker
  runs.length = 0
  await clock.advance(60_000)
  expect(opened).toEqual(['Boss'])
  expect(runs.map(r => r.includes('--worker') ? 'worker' : r.includes('--session-start') ? 'boss-start' : 'boss')).toEqual(['boss-start'])
  expect(commands).toEqual(["Open the boss pane (or this worker's) and refresh it now"])  // registered once, at the start

  // From now on one boss timer, no worker refresh, and /boss-deck does not switch again.
  runs.length = 0
  await clock.advance(60_000)
  expect(runs.map(r => r.includes('--worker') ? 'worker' : 'boss')).toEqual(['boss'])
  expect(await $.command.run({ command: 'boss-deck', args: '' } as Parameters<typeof $.command.run>[0])).toEqual({ text: 'Boss pane refreshed.' })
  expect(opened).toEqual(['Boss', 'Boss'])

  // The marker going away never turns the boss back into a worker.
  local = ''
  runs.length = 0
  await clock.advance(60_000)
  expect(runs.map(r => r.includes('--worker') ? 'worker' : 'boss')).toEqual(['boss'])
})

/** A session outside any host (no host id): CLAUDE.local.md as `local()` says, the data script's runs in `runs`. */
function plain(on: On, local: () => string, opened: string[], runs: string[][], commands: string[]) {
  const clock = mock.clock(on)
  on('fs.read', async () => {
    if (!local()) throw new Error('no CLAUDE.local.md')
    return { value: local() } as never
  })
  on('session.cwd', async () => ({ value: '/w/plain' }))
  on('session.start', async () => ({ cwd: '/w/plain' }))
  on('command.register', async (_$, e) => (commands.push(e.name), { value: { command: e.name } }) as never)
  on('ui.open', async (_$, e) => (opened.push(e.title ?? ''), { value: { isPlaced: true as const } }))
  on('process.run', async (_$, e) => {
    if (e.argv[0] === 'git') return { value: { exitCode: 128, stdout: '', stderr: 'not a git repository', isStdoutTruncated: false, isStderrTruncated: false } }
    const sess = e.argv.includes('boss-host-session')
    if (!sess) runs.push([...e.argv])
    const stdout = JSON.stringify(sess ? {} : { at: 0, next: '', attention: [], workers: [], watchers: [], prs: [], board: {} })
    return { value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  return clock
}

test('a session that is neither a boss nor a worker has /boss-deck, and it says how to set one up', async ($, on) => {
  const opened: string[] = []
  const runs: string[][] = []
  const commands: string[] = []
  const clock = plain(on, () => '', opened, runs, commands)
  await $.session.start({ cwd: '/w/plain', surface: 'terminal', isInteractive: true })
  expect(commands).toEqual(['boss-deck'])
  expect(await $.command.run({ command: 'boss-deck', args: '' } as Parameters<typeof $.command.run>[0])).toEqual({ text: 'Not a boss here: run /boss to set one up.' })
  await clock.advance(60_000)
  expect(opened).toEqual([])
  expect(runs).toEqual([])  // no data script, no heartbeat: only a read of CLAUDE.local.md each tick
})

test('a session with no host id that /boss onboard makes the boss gets the pane on the next tick, without a restart', async ($, on) => {
  let local = ''
  const opened: string[] = []
  const runs: string[][] = []
  const clock = plain(on, () => local, opened, runs, [])
  await $.session.start({ cwd: '/w/plain', surface: 'terminal', isInteractive: true })
  await clock.advance(60_000)
  expect(opened).toEqual([])

  local = '# Boss workspace\n'  // what onboarding writes with no host session id
  await clock.advance(60_000)
  expect(opened).toEqual(['Boss'])
  expect(runs.map(r => r.includes('--session-start'))).toEqual([true])
  runs.length = 0
  await clock.advance(60_000)
  expect(runs.length).toBe(1)  // one boss refresh per tick: the re-check timer is gone
  expect(await $.command.run({ command: 'boss-deck', args: '' } as Parameters<typeof $.command.run>[0])).toEqual({ text: 'Boss pane refreshed.' })
})
