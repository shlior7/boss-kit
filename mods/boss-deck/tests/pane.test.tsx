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
    { id: 'ws-me', workspace: 'ws-me', domain: '', me: true, next: '', working: 1, forYou: 0, heartbeat: 0, stale: false, state: [], sessions: [{ id: 'ab120000', title: 'api research', state: 'idle', ageS: 600, task: 'research-1: map the api' }] },
    { id: 'ws-co', workspace: 'ws-co', domain: 'checkout', me: false, next: 'merge #61', working: 1, forYou: 2, heartbeat: 0, stale: false, state: [] },
  ],
  others: [{ id: 'ws-a', project: 'gadgets', workspace: 'ws-a', working: 1, forYou: 0 }],
  mail: { count: 1, dir: '/nonexistent', items: [{ id: 'm1', kind: 'question', from: 'gadgets', subject: 'is #42 safe?' }] },
}

const SESSION = { kind: 'hosta', id: 'ws-me', terminal: '' }
const out = (v: unknown) => ({ value: { exitCode: 0, stdout: JSON.stringify(v), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })

test('the pane passes its workspace, and draws its inbox, its bosses, one WORKERS section and the board', async ($, on) => {
  const runs: string[][] = []
  mock.clock(on)
  on('session.cwd', async () => ({ value: '/w/boss' }))
  on('ui.open', async () => ({ value: { isPlaced: true as const } }))
  on('process.run', async (_$, e) => {
    if (e.argv.includes('boss-host-session')) return out(SESSION)
    runs.push([...e.argv])
    return { value: { exitCode: 0, stdout: JSON.stringify(DECK), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  // The engine stamps origin and presentation.
  await $.command.run({ command: 'boss-deck', args: '' } as Parameters<typeof $.command.run>[0])
  expect(runs[0]?.slice(-4)).toEqual(['--cwd', '/w/boss', '--workspace', 'ws-me'])
  expect(runs[0]?.slice(-6, -4)).toEqual(['--host-kind', 'hosta'])

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
  // this boss's own workspace is never a worker; its other agent sessions sit in its BOSSES accordion
  await ui.press({ key: 'peek-b-ws-me' })
  const sess = (await ui.findAll({ type: 'Text' })).map(t => t.text ?? '')
  expect(sess).toContain('api research · idle · 10m · research-1: map the api')
})

test('the pane refreshes at once after the boss messages or dispatches through boss-host, skipping the PR cache', async ($, on) => {
  const runs: string[][] = []
  mock.clock(on)
  on('fs.read', async () => ({ value: '# Boss workspace ws-me\n' }))
  on('session.cwd', async () => ({ value: '/w/boss' }))
  on('session.start', async () => ({ cwd: '/w/boss' }))
  on('command.register', async (_$, e) => ({ value: { command: e.name } }) as never)
  on('ui.open', async () => ({ value: { isPlaced: true as const } }))
  on('process.run', async (_$, e) => {
    if (e.argv.includes('boss-host-session')) return out(SESSION)
    runs.push([...e.argv])
    return out(DECK)
  })
  on('tool.call', async () => ({ result: { stdout: '', stderr: '', interrupted: false }, text: '' }) as never)
  await $.session.start({ cwd: '/w/boss', surface: 'terminal', isInteractive: true })
  const before = runs.filter(r => r.includes('--fresh')).length
  await $.tool.call({ tool: 'Bash', command: 'boss-host send 1a2b3c4d-full --text "also cover 429"' })
  await $.tool.call({ tool: 'Bash', command: 'ls' })
  // The send's own refresh runs unawaited; one awaited refresh lets it settle before the test ends.
  await $.command.run({ command: 'boss-deck', args: '' } as Parameters<typeof $.command.run>[0])
  expect(runs.filter(r => r.includes('--fresh')).length).toBe(before + 1)
})

test('the boss pane shows an attention line once the kit on disk moves past the one it loaded, and the PR drift note on a row', async ($, on) => {
  let kit = 'a1b2c3d'
  const behind = { ...PR57, behind: 3 }
  mock.clock(on)
  on('fs.read', async () => ({ value: '# Boss workspace ws-me\n' }))
  on('session.cwd', async () => ({ value: '/w/boss' }))
  on('session.start', async () => ({ cwd: '/w/boss' }))
  on('command.register', async (_$, e) => ({ value: { command: e.name } }) as never)
  on('ui.open', async () => ({ value: { isPlaced: true as const } }))
  on('process.run', async (_$, e) => {
    if (e.argv.includes('boss-host-session')) return out(SESSION)
    const deck: Deck = { ...DECK, kit, workers: [DECK.workers[0]!, { ...DECK.workers[1]!, pr: behind }], prs: [DECK.prs[0]!, DECK.prs[1]!, behind] }
    return { value: { exitCode: 0, stdout: JSON.stringify(deck), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  const run = () => $.command.run({ command: 'boss-deck', args: '' } as Parameters<typeof $.command.run>[0])
  await $.session.start({ cwd: '/w/boss', surface: 'terminal', isInteractive: true })
  await run()
  const ui = await $.ui.mount({ plugin: 'boss-deck', surface: 'terminal', component: 'Pane', requestId: 'boss-deck', props: {} as never })
  const texts = async () => (await ui.findAll({ type: 'Text' })).map(t => t.text ?? '')
  expect(await texts()).not.toContain('kit updated · run /reload-plugins')
  kit = 'e4f5a6b'
  await run()
  const after = await texts()
  expect(after).toContain('kit updated · run /reload-plugins')
  expect(after.find(t => t.startsWith('web-login'))?.replace(/ +/g, ' ')).toBe('web-login #57 in review · 3 behind main · waiting on review')
})

test('a boss button submits exactly its configured prompt to the session, once, and toasts it; a worker button fills its fields', async ($, on) => {
  const buttons = [{ label: 'Status', prompt: 'Status: what needs me, in plain words.' }, { label: 'Mail', prompt: 'Read the inbox.' }]
  const workerButtons = [{ label: 'Verify', prompt: 'Verify {name} ({id}) PR {pr} on {branch}. Ask before merging.' }]
  const sent: { text: string; origin?: unknown }[] = []
  const toasts: string[] = []
  const runs: string[][] = []
  mock.clock(on)
  on('session.cwd', async () => ({ value: '/w/boss' }))
  on('ui.open', async () => ({ value: { isPlaced: true as const } }))
  on('ui.toast', async (_$, e) => (toasts.push(e.text), { value: undefined }))
  on('prompt.submit', async (_$, e) => (sent.push({ text: e.text, origin: e.origin }), { text: e.text, origin: e.origin }))
  on('process.run', async (_$, e) => {
    if (e.argv.includes('boss-host-session')) return out(SESSION)
    runs.push([...e.argv])
    return out({ ...DECK, buttons, workerButtons })
  })
  await $.command.run({ command: 'boss-deck', args: '' } as Parameters<typeof $.command.run>[0])
  const ui = await $.ui.mount({ plugin: 'boss-deck', surface: 'terminal', component: 'Pane', requestId: 'boss-deck', props: {} as never })
  const texts = (await ui.findAll({ type: 'Text' })).map(t => t.text ?? '')
  expect(texts.slice(texts.indexOf('Status'), texts.indexOf('Status') + 2)).toEqual(['Status', 'Mail'])
  const before = runs.length

  await ui.press({ key: 'ask-Status' })
  expect(sent).toEqual([{ text: 'Status: what needs me, in plain words.', origin: { kind: 'plugin', name: 'boss-deck', asUser: true } }])
  expect(toasts).toEqual(['sent: Status: what needs me, in plain…'])  // one line: clipped to the toast box
  expect(runs.length).toBe(before)  // nothing else ran: no process, no merge

  // A worker's accordion: its own buttons, fields filled; the PR-only rows have none.
  await ui.press({ key: 'peek-w-5e6f7a8b' })
  await ui.press({ key: 'ask-w-5e6f7a8b-Verify' })
  expect(sent[1]?.text).toBe('Verify web-login (ws-2) PR acme/widgets#57 on c. Ask before merging.')
  await ui.press({ key: 'peek-p-acme/widgets-7' })
  expect((await ui.findAll({ type: 'Text' })).map(t => t.text)).not.toContain('Verify')
})

test('the header names the page provider, a worker\'s accordion lists its pages and proof once each, and the boss lists its own', async ($, on) => {
  const pages = [{ url: 'https://example.com/page', title: 'after run', at: 2 }, { url: 'https://example.com/before', title: 'before run', at: 1 }]
  const deck: Deck = {
    ...DECK, pagesTo: 'acme-pages',
    workers: [DECK.workers[0]!, { ...DECK.workers[1]!, pages }],
    bosses: [{ ...DECK.bosses![0]!, pages: [{ url: 'https://example.com/review', title: 'review 2026-01-02', at: 3 }] }],
  }
  mock.clock(on)
  on('session.cwd', async () => ({ value: '/w/boss' }))
  on('ui.open', async () => ({ value: { isPlaced: true as const } }))
  on('process.run', async (_$, e) => (e.argv.includes('boss-host-session') ? out(SESSION) : out(deck)))
  await $.command.run({ command: 'boss-deck', args: '' } as Parameters<typeof $.command.run>[0])
  const ui = await $.ui.mount({ plugin: 'boss-deck', surface: 'terminal', component: 'Pane', requestId: 'boss-deck', props: {} as never })
  const texts = async () => (await ui.findAll({ type: 'Text' })).map(t => t.text ?? '')
  expect((await texts()).filter(t => t.startsWith('pages →'))).toEqual(['pages → acme-pages'])
  await ui.press({ key: 'peek-w-5e6f7a8b' })
  expect((await texts()).filter(t => t.endsWith('↗'))).toEqual(['after run ↗', 'before run ↗', 'demo ↗', 'open workspace ↗', 'open on GitHub ↗'])
  await ui.press({ key: 'peek-b-ws-me' })
  expect((await texts()).filter(t => t.endsWith('↗'))).toEqual(['review 2026-01-02 ↗', 'open workspace ↗'])
})

test('no provider set: no pages line', async ($, on) => {
  mock.clock(on)
  on('session.cwd', async () => ({ value: '/w/boss' }))
  on('ui.open', async () => ({ value: { isPlaced: true as const } }))
  on('process.run', async (_$, e) => (e.argv.includes('boss-host-session') ? out(SESSION) : out(DECK)))
  await $.command.run({ command: 'boss-deck', args: '' } as Parameters<typeof $.command.run>[0])
  const ui = await $.ui.mount({ plugin: 'boss-deck', surface: 'terminal', component: 'Pane', requestId: 'boss-deck', props: {} as never })
  expect((await ui.findAll({ type: 'Text' })).some(t => (t.text ?? '').startsWith('pages →'))).toBe(false)
})
