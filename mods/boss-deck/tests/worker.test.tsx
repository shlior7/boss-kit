import { expect, mock, test } from 'claude-code/testing'
import type { On, SessionMessage } from 'claude-code'

import { workerDetails } from '../hooks/details'
import { activity, newMsgs, progress, prParts, sentMessages, taskList, workerWarnings } from '../hooks/worker'
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

test('a sent message is logged with its workspace; a key-only send is not', () => {
  const cmd = `superset terminals send --workspace 1a2b3c4d-full --terminal t1 --keys ctrl+u --local && superset terminals send --workspace 1a2b3c4d-full --terminal t1 --text "also cover the \\"429\\" case" --local`
  expect(sentMessages(cmd)).toEqual([{ ws: '1a2b3c4d-full', text: 'also cover the "429" case' }])
  expect(sentMessages(`superset terminals send --workspace w2 --text 'x'`)).toEqual([{ ws: 'w2', text: 'x' }])
  expect(sentMessages('superset terminals send --workspace w2 --keys enter')).toEqual([])
  expect(sentMessages('superset terminals read --workspace w2')).toEqual([])
  expect(sentMessages(`superset terminals send --workspace w2 --text "${'a'.repeat(300)}"`)[0]?.text.length).toBe(200)
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

function session(on: On, deck: WorkerDeck | object, opened: string[], runs: string[][]) {
  mock.env(on, { SUPERSET_WORKSPACE_ID: '1a2b3c4d-full' })
  mock.clock(on)
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
    runs.push([...e.argv])
    return { value: { exitCode: 0, stdout: JSON.stringify(deck), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
}

test('no dispatch row for this workspace: no pane', async ($, on) => {
  const opened: string[] = []
  const runs: string[][] = []
  session(on, { at: 0, worker: null }, opened, runs)
  await $.session.start({ cwd: '/w/worker', surface: 'terminal', isInteractive: true })
  const said = await $.command.run({ command: 'boss-deck', args: '' } as Parameters<typeof $.command.run>[0])
  expect(runs.some(r => r.includes('--worker'))).toBe(true)
  expect(opened).toEqual([])
  expect(said).toEqual({ text: 'No boss ledger has a dispatch row for this workspace.' })
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

  const ui = await $.ui.mount({ plugin: 'boss-deck', surface: 'terminal', component: 'Pane', requestId: 'boss-deck', props: {} as never })
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
