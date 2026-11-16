import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Boss, Deck, DeckButton, Detail, Live, Pr, ProofLink, Worker, WorkerDeck } from '../types'
import { KIT_STALE, ago, bossDetails, buttons, bossRow, footer, isActive, isBoss, kitStale, mailContext, pageLinks, prDetails, prRow, rank, workerDetails, workerRow } from './details'
import type { PrView, Row } from './details'
import { activity, newMsgs, progress, prParts, stateParts, taskList, workerWarnings } from './worker'

const PANE = 'boss-deck'
const TITLE = 'Boss'
const WORKER_TITLE = 'Worker'
// The kit root: $BOSS_KIT_HOME, else ~/.claude/boss-kit. A shell expands it so the mod needs no env access.
const DATA_CMD = ['sh', '-c', 'exec python3 "${BOSS_KIT_HOME:-$HOME/.claude/boss-kit}/bin/boss-deck-data.py" "$@"', 'boss-deck-data']
// bin/boss-host as this session: its host plugin and id first, then boss-host's own arguments (open, screen).
const HOST_CMD = ['sh', '-c', 'BOSS_HOST_KIND="$1" BOSS_SESSION_ID="$2"; export BOSS_HOST_KIND BOSS_SESSION_ID; shift 2; exec python3 "${BOSS_KIT_HOME:-$HOME/.claude/boss-kit}/bin/boss-host" "$@"', 'boss-host']
// This session on its host, {kind, id, terminal}: boss-host reads the env this process passes on, so the mod reads none.
const HOST_SESSION_CMD = ['sh', '-c', 'exec python3 "${BOSS_KIT_HOME:-$HOME/.claude/boss-kit}/bin/boss-host" session', 'boss-host-session']
const REFRESH_MS = 60_000
// The worker view's FROM BOSS rows.
const MSG_ROWS = 3
// A PR untouched this long folds into one 'stale' line.
const STALE_PR_DAYS = 10
// A toast's line in a terminal: longer wraps in the toast box.
const TOAST_COLS = 38
// Unread messages listed in the inbox before it folds the rest into "+N more".
const INBOX_ROWS = 5
// Change a tag when its value's fields change: it declines what an earlier version stored.
const deck = atom({ plugin: 'boss-deck', key: 'deck' } as const, null, { shape: 'deck-11' })
const peek = atom({ plugin: 'boss-deck', key: 'peek' } as const, null, { shape: 'peek-4' })
const mine = atom({ plugin: 'boss-deck', key: 'mine' } as const, null, { shape: 'mine-3' })
const live = atom({ plugin: 'boss-deck', key: 'live' } as const, null, { shape: 'live-1' })
// Which pane this session draws: the boss's, a dispatched worker's own, or none. session.start sets it again on a reload.
let role: 'boss' | 'worker' | undefined
let workerShown = false
// The kit's HEAD when this module loaded (the first one a refresh reports); the pane warns once the disk moves past it.
let loadedKit: string | undefined

// Quiet by design: grey text, color only where it means something: stage marks and what needs attention.

type Self = { id?: string; kind?: string; term?: string; failed?: true }
let hostSession: Promise<Self> | undefined
/** This session on its host (its plugin, id and own terminal), {} outside any; asked once per session start. A failed
 * lookup is `failed`, not outside a host, and is never kept: the next call asks again. */
function self($: EngineInterface): Promise<Self> {
  const asked = (hostSession ??= $.process.run(HOST_SESSION_CMD, { timeoutMs: 20_000 }).then(r => {
    try {
      if (r.exitCode !== 0) return { failed: true as const }
      const v = JSON.parse(r.stdout) as { kind?: string; id?: string; terminal?: string }
      return v?.id ? { id: v.id, kind: v.kind, term: v.terminal || undefined } : {}
    } catch {
      return { failed: true as const }
    }
  }))
  void asked.then(s => {
    if (s.failed && hostSession === asked) hostSession = undefined
  })
  return asked
}
const kindArgs = (s: Self) => (s.kind ? ['--host-kind', s.kind] : [])
const idArgs = (s: Self) => (s.id ? ['--workspace', s.id] : [])

async function refresh($: EngineInterface, sessionStart = false, skipCache = false) {
  // The session's own workspace (or session) and directory, so the script resolves the boss the session's shell does,
  // and its own terminal, so the boss's sessions list leaves it out.
  const me = await self($)
  const argv = [...DATA_CMD, ...(me.term ? ['--terminal', me.term] : []), ...kindArgs(me), '--cwd', await $.session.cwd(), ...idArgs(me), ...(sessionStart ? ['--session-start'] : []), ...(skipCache ? ['--fresh'] : [])]
  const { exitCode, stdout, stderr } = await $.process.run(argv, { timeoutMs: 90_000 })
  const at = Math.floor((await $.clock.now()) / 1000)
  const fresh: Deck =
    exitCode === 0
      ? JSON.parse(stdout)
      : { at, next: '', attention: [], workers: [], watchers: [], prs: [], board: {}, error: stderr.slice(0, 200) }
  loadedKit ??= fresh.kit || undefined
  await update($, deck, () => fresh)
}

/** The worker's own session as the pane reads it: task list, latest step and context; `patch` sets the turn fields. */
async function track($: EngineInterface, patch: Partial<Live> = {}) {
  const msgs = await $.session.messages()
  // A host that refuses the read (a test runner's) leaves the context % out.
  const ctx = (await $.session.usage().catch(() => null))?.context.percent ?? null
  await update($, live, cur => ({ busy: false, turnAt: 0, ...cur, ...patch, tasks: taskList(msgs), now: activity(msgs), ctx }))
}

/** The worker view's data; its task progress goes along for the boss to read. Opens the pane once a dispatch row exists. */
async function workerRefresh($: EngineInterface, patch: Partial<Live> = {}) {
  const me = await self($)
  if (!me.id) return
  await track($, patch)
  const status = JSON.stringify(progress((await read($, live))?.tasks ?? []))
  const argv = [...DATA_CMD, ...kindArgs(me), '--worker', ...idArgs(me), '--cwd', await $.session.cwd(), '--status', status]
  const { exitCode, stdout, stderr } = await $.process.run(argv, { timeoutMs: 90_000 })
  const got: WorkerDeck | null = exitCode === 0 ? JSON.parse(stdout) : null
  loadedKit ??= got?.kit || undefined
  await update($, mine, cur => got ?? (cur ? { ...cur, error: stderr.slice(0, 200) } : null))
  if (got?.worker && !workerShown) {
    workerShown = true
    void $.ui.open({ id: PANE, title: WORKER_TITLE })
  }
}

async function openUrl($: EngineInterface, url: string) {
  await $.process.run(['open', url], { timeoutMs: 10_000 })
}

async function openWorkspace($: EngineInterface, id: string) {
  const me = await self($)
  await $.process.run([...HOST_CMD, me.kind ?? '', me.id ?? '', 'open', id], { cwd: await $.session.cwd(), timeoutMs: 20_000 })
}

/** A pane button's click: its prompt goes to this session as if the user typed it, and a toast shows what went.
 * It only asks: whatever the prompt leads to, the boss's own rules gate it (template section 3). */
async function send($: EngineInterface, prompt: string) {
  const line = `sent: ${prompt.replace(/\s+/g, ' ').trim()}`
  $.ui.toast(line.length > TOAST_COLS ? `${line.slice(0, TOAST_COLS - 1)}…` : line)
  await $.prompt.submit({ text: prompt, asUser: true })
}

/** Unread mail now: the inbox dir only, so a prompt costs one listing. */
async function unreadMail($: EngineInterface) {
  const d = await read($, deck)
  if (!d?.mail?.dir) return undefined
  const entries = await $.fs.list(d.mail.dir).catch(() => [])
  const count = entries.filter(f => f.kind === 'file' && f.name.endsWith('.json')).length
  return mailContext(count, d.mail.items)
}

/** Toggle one expanded row: a worker's, a PR's or a boss's details under it. */
async function toggle($: EngineInterface, key: string, load: () => Promise<{ rows: Detail[]; links?: ProofLink[] }>) {
  const shown = await read($, peek)
  if (shown?.key === key) return update($, peek, () => null)
  await update($, peek, () => ({ key, rows: [{ label: '', value: 'loading…' }] }))
  const got = await load().catch(() => ({ rows: [{ label: 'error', value: 'could not load', color: 'error' }] }))
  // Closed, or another row opened, while this one loaded: keep what is shown now.
  await update($, peek, cur => (cur?.key === key ? { key, ...got } : cur))
}

async function prView($: EngineInterface, p: Pr) {
  const fields = 'statusCheckRollup,mergeable,mergeStateStatus,additions,deletions,changedFiles,updatedAt,headRefOid,latestReviews,reviewRequests'
  const { stdout } = await $.process.run(['gh', 'pr', 'view', String(p.num), '--repo', p.repo, '--json', fields], { timeoutMs: 30_000 })
  return prDetails(p, JSON.parse(stdout) as PrView, Math.floor((await $.clock.now()) / 1000))
}

/** A workspace's details and its PR's, in one accordion; the proof links of both. */
async function workerPeek($: EngineInterface, w: Worker) {
  // The worker's screen where its host can read one; otherwise nothing, and the worker's status file says what it is doing.
  const me = await self($)
  const [read, pr] = await Promise.all([
    w.id && w.term ? $.process.run([...HOST_CMD, me.kind ?? '', me.id ?? '', 'screen', w.id, w.term], { cwd: await $.session.cwd(), timeoutMs: 20_000 }) : undefined,
    w.pr ? prView($, w.pr).catch(() => [{ label: 'pr', value: 'could not load', color: 'error' }]) : [],
  ])
  const screen = read?.exitCode === 0 ? read.stdout : ''
  return { rows: workerDetails(w, screen, pr), links: pageLinks(w.pages, w.proof, w.pr?.proof ?? []) }
}

/** Picks this session's role and starts its pane. A failed host lookup decides nothing: it asks again a minute later. */
async function start($: EngineInterface) {
  const local = await $.fs.read('CLAUDE.local.md').catch(() => '')
  const me = await self($)
  if (me.failed) {
    $.clock.after(REFRESH_MS, () => void start($))
    return
  }
  // Not the boss (a copy of its CLAUDE.local.md, another workspace on its checkout, any other session): a host session
  // gets the worker view once a boss's ledger has its dispatch row; anything else stays quiet.
  if (!isBoss(local, me.id)) {
    if (!me.id) return
    role = 'worker'
    workerShown = false
    loadedKit = undefined
    await $.command.register({ name: 'boss-deck', description: 'Open this worker\'s pane and refresh it now' })
    void workerRefresh($)
    $.clock.every(REFRESH_MS, () => void workerRefresh($))
    return
  }

  role = 'boss'
  loadedKit = undefined
  await $.command.register({ name: 'boss-deck', description: 'Open the boss pane and refresh it now' })
  void $.ui.open({ id: PANE, title: TITLE })
  void refresh($, true)
  $.clock.every(REFRESH_MS, () => void refresh($))
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    hostSession = undefined
    await start($)
    return next(e)
  })

  on('command.run', { command: 'boss-deck' }, async $ => {
    if (role === 'worker') {
      await workerRefresh($)
      if (!(await read($, mine))?.worker) return { text: 'No boss ledger has a dispatch row for this workspace.' }
      await $.ui.open({ id: PANE, title: WORKER_TITLE })
      return { text: 'Worker pane refreshed.' }
    }
    await $.ui.open({ id: PANE, title: TITLE })
    await refresh($)

    return { text: 'Boss pane refreshed.' }
  })

  // While boss mail is unread, every prompt carries one context line naming it (never shown to the user).
  on('prompt.submit', async ($, e, next) => {
    if (e.command || e.isMeta) return next(e)
    // A worker's turn begins: the boss's messages before it are read.
    if (role === 'worker') {
      const at = await $.clock.now()
      void update($, live, cur => ({ tasks: [], now: '', ctx: null, ...cur, busy: true, turnAt: at }))
    }
    const note = await unreadMail($)
    return next(note ? { ...e, context: [...(e.context ?? []), note] } : e)
  })

  // Refresh right after the boss dispatches, messages, merges or comments, not only on the timer (boss-host logs the messages).
  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const ran = await next(e)
    if (role !== 'boss') return ran
    if (/boss-host (send|create|archive)|boss-merge|gh pr (merge|edit|comment)|boss-sync/.test(e.command)) void refresh($, false, true)

    return ran
  })

  // A worker's own tool calls move its task list and "now" line; its turn's end refreshes the view and its status file.
  on('tool.call', async ($, e, next) => {
    const ran = await next(e)
    if (role === 'worker' && e.agentId === undefined) void track($)
    return ran
  })
  on('turn.complete', async ($, e, next) => {
    if (role === 'worker' && e.agentId === undefined) void workerRefresh($, { busy: false })
    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const now = Math.floor((await $.clock.now()) / 1000)

    const cell = (w: number, child: unknown) => (
      <Box width={w} flexShrink={0}>
        {child as string}
      </Box>
    )
    const rest = (child: unknown) => (
      <Box flexGrow={1} flexShrink={1}>
        {child as string}
      </Box>
    )
    const text = (v: string, dim: boolean, color?: string) => (
      <Text dimColor={dim} color={color} wrap="truncate-end">
        {v}
      </Text>
    )
    const section = (name: string, note: string) => (
      <Box flexDirection="row" justifyContent="space-between" marginTop={1}>
        <Text dimColor bold>
          {name.toUpperCase()}
        </Text>
        <Text dimColor>{note}</Text>
      </Box>
    )
    // A plain Button per link: terminals without OSC 8 would print a Link's whole URL.
    const linkButton = (k: string, label: string, url: string) => (
      <Button plain key={k} onPress={() => void openUrl($, url)}>
        <Text color="suggestion">{label}</Text>
      </Button>
    )
    const ask = (k: string, b: DeckButton) => (
      <Button plain key={k} onPress={() => void send($, b.prompt)}>
        <Text color="suggestion">{b.label}</Text>
      </Button>
    )
    const askRow = (k: string, bs: DeckButton[]) =>
      bs.length > 0 && (
        <Box flexDirection="row" columnGap={2} flexWrap="wrap">
          {bs.map(b => ask(`ask-${k}${b.label}`, b))}
        </Box>
      )
    type Open = { key: string; label: string; press: () => void }
    // The expanded row's ways out (proof, the workspace, GitHub) share one line, wrapping only when the pane is too narrow.
    // A worker's prompt buttons (asks) sit on their own line above them.
    const details = (rows: Detail[], links: ProofLink[], opens: Open[], asks: unknown) => (
      <Box flexDirection="column" paddingLeft={4} marginBottom={1}>
        {rows.map(r => (
          <Box flexDirection="row">
            {cell(9, text(r.label, true))}
            {rest(text(r.value, !r.color, r.color))}
          </Box>
        ))}
        {asks as string}
        {(links.length > 0 || opens.length > 0) && (
          <Box flexDirection="row" columnGap={2} flexWrap="wrap">
            {links.map((l, i) => linkButton(`proof-${l.url}-${i}`, `${l.label} ↗`, l.url))}
            {opens.map(o => (
              <Button plain key={o.key} onPress={o.press}>
                <Text color="suggestion">{o.label}</Text>
              </Button>
            ))}
          </Box>
        )}
      </Box>
    )
    const parts = (ps: { text: string; color?: string }[]) => (
      <Text dimColor wrap="truncate-end">
        {ps
          .filter(p => p.text)
          .map((p, n) => (
            <Text dimColor={!p.color} color={p.color}>{(n ? ' · ' : '') + p.text}</Text>
          ))}
      </Text>
    )

    // A worker session: its own dispatch, top to bottom; empty sections drop out.
    const mw = await read($, mine)
    if (role === 'worker' || mw?.worker) {
      const v = mw?.worker
      if (!v) return <Text dimColor>{mw?.error ? `data error: ${mw.error}` : 'loading…'}</Text>
      const l = await read($, live)
      const tasks = l?.tasks ?? []
      const fresh = newMsgs(v, l)
      const warn = workerWarnings(v, l, kitStale(loadedKit, mw?.kit))
      const field = (k: string, child: unknown) => (
        <Box flexDirection="row">
          {cell(7, text(k, true))}
          {rest(child)}
        </Box>
      )
      // Proof links not already listed under PAGES.
      const links = pageLinks(undefined, v.pr?.proof ?? [], v.proof).filter(x => !(v.pages ?? []).some(p => p.url === x.url))
      const MARK = { completed: ['✓', 'success'], in_progress: ['●', 'suggestion'], pending: ['○', undefined] } as const
      return (
        <Box flexDirection="column" paddingX={1}>
          {mw?.error && text(`data error: ${mw.error}`, false, 'error')}
          <Box flexDirection="row" justifyContent="space-between" columnGap={2}>
            <Box flexShrink={1}>
              <Text bold wrap="truncate-end">{`WORKER  ${v.name} · ${v.task}`}</Text>
            </Box>
            <Box flexShrink={0}>
              <Text dimColor>{`boss: ${v.project}`}</Text>
            </Box>
          </Box>
          {v.pagesTo && text(`pages → ${v.pagesTo}`, true)}
          {field('goal', text(v.goal, false))}
          {v.pr && field('pr', parts(prParts(v.pr)))}
          {field('state', parts(stateParts(v, l, ago, now)))}

          {tasks.length > 0 && section('tasks', `${tasks.filter(t => t.status === 'completed').length} of ${tasks.length} done`)}
          {tasks.map(t => (
            <Box flexDirection="row">
              {cell(2, text(MARK[t.status][0], t.status === 'pending', MARK[t.status][1]))}
              {rest(text(t.status === 'in_progress' ? t.active || t.subject : t.subject, t.status !== 'in_progress'))}
            </Box>
          ))}

          {v.delivered.length > 0 && section('delivered', `${v.delivered.length} newest`)}
          {v.delivered.map(r => field(r.hm, text(r.kind === 'commit' ? r.text : [r.kind, r.text].filter(Boolean).join('  '), true)))}

          {(v.pages?.length ?? 0) > 0 && section('pages', '.boss-worker/pages.jsonl')}
          {(v.pages ?? []).map((p, i) => field(ago(Math.max(0, now - p.at)), linkButton(`page-${p.url}-${i}`, `${p.title} ↗`, p.url)))}

          {v.notes.length > 0 && section('notes', '.boss-worker/notes.md')}
          {v.notes.map(n => text(n, true))}

          {v.msgs.length > 0 && section('from boss', `${fresh} new`)}
          {v.msgs.slice(0, MSG_ROWS).map((m, i) => field(m.hm, text(m.text, i >= fresh)))}

          {warn.length > 0 && <Box marginTop={1}>{text(`! ${warn.join(' · ')}`, false, 'warning')}</Box>}
          <Box flexDirection="row" justifyContent="space-between" columnGap={2} marginTop={1}>
            <Box flexDirection="row" flexWrap="wrap" columnGap={2} flexShrink={1}>
              {links.map((x, i) => linkButton(`proof-${x.url}-${i}`, `${x.label} ↗`, x.url))}
              {v.pr?.url && linkButton('pr', 'PR ↗', v.pr.url)}
              {v.boss.workspace && (
                <Button plain key="boss" onPress={() => void openWorkspace($, v.boss.workspace)}>
                  <Text color="suggestion">boss ↗</Text>
                </Button>
              )}
            </Box>
            <Box flexShrink={0}>
              <Text dimColor>{[l?.ctx != null ? `ctx ${l.ctx}%` : '', `${ago(Math.max(0, now - (mw?.at ?? now)))} ago`].filter(Boolean).join(' · ')}</Text>
            </Box>
          </Box>
        </Box>
      )
    }

    const d = await read($, deck)
    if (!d) return <Text dimColor>loading…</Text>
    const shown = await read($, peek)

    const openWs = (id: string): Open[] => (id ? [{ key: `open-${id}`, label: 'open workspace ↗', press: () => void openWorkspace($, id) }] : [])
    const openGh = (url?: string): Open[] => (url ? [{ key: `gh-${url}`, label: 'open on GitHub ↗', press: () => void openUrl($, url) }] : [])

    // A PR no workspace owns is its own row; one untouched for STALE_PR_DAYS folds into one quiet line.
    const loose = d.prs.filter(p => !p.ws)
    const cutoff = (now - STALE_PR_DAYS * 86400) * 1000
    const isStale = (p: Pr) => !!p.updated && Date.parse(p.updated) < cutoff
    const stale = loose.filter(isStale)
    // Active workspaces first, then the idle ones, then the PR-only rows. Row order is hotkey order.
    const workers = [...d.workers].sort((a, b) => rank(a) - rank(b))
    const active = workers.filter(isActive).length
    type Item = { key: string; row: Row; load: () => Promise<{ rows: Detail[]; links?: ProofLink[] }>; opens: Open[]; asks?: DeckButton[] }
    const items: Item[] = [
      ...workers.map(w => ({ key: `w-${w.ws}`, row: workerRow(w, now), load: () => workerPeek($, w), opens: [...openWs(w.id), ...openGh(w.pr?.url)], asks: buttons(d.workerButtons, w) })),
      ...loose
        .filter(p => !isStale(p))
        .map(p => ({ key: `p-${p.repo}-${p.num}`, row: prRow(p, now), load: async () => ({ rows: await prView($, p), links: p.proof }), opens: openGh(p.url) })),
    ]
    const bosses: Item[] = (d.bosses ?? []).map((b: Boss) => ({
      key: `b-${b.id}`, row: bossRow(b, now), load: async () => ({ rows: bossDetails(b, now), links: pageLinks(b.pages) }), opens: openWs(b.workspace),
    }))

    // One quiet line per row, never wrapping: the mark, then the whole row is a button that expands it.
    const row = (it: Item, hotkey?: number) => {
      const r = it.row
      const open = shown?.key === it.key
      const nameW = hotkey ? 15 : 18
      return (
        <Box flexDirection="column">
          <Box flexDirection="row">
            {cell(2, text(r.mark, r.dim && !r.markColor, r.markColor))}
            {/* A hotkey's "1: " takes 3 of the name's 18 cells. */}
            {rest(
              <Button plain key={`peek-${it.key}`} hotkey={hotkey ? String(hotkey) : undefined} onPress={() => void toggle($, it.key, it.load)}>
                <Text dimColor={r.dim} bold={open} wrap="truncate-end">
                  {r.name.slice(0, nameW - 2).padEnd(nameW)}
                  {r.tag && r.tag.slice(0, 8).padEnd(10)}
                  {r.parts
                    .filter(p => p.text)
                    .map((p, n) => (
                      <Text color={p.color}>{(n ? ' · ' : '') + p.text}</Text>
                    ))}
                </Text>
              </Button>,
            )}
          </Box>
          {open && shown && details(shown.rows, shown.links ?? [], it.opens, askRow(`${it.key}-`, it.asks ?? []))}
        </Box>
      )
    }

    return (
      <Box flexDirection="column" paddingX={1}>
        {d.error && text(`data error: ${d.error}`, false, 'error')}
        {d.review && linkButton('review', `review ↗ ${d.review.date}`, d.review.url)}
        <Text bold wrap="wrap">
          {d.next || 'Nothing needs you.'}
        </Text>
        {d.pagesTo && text(`pages → ${d.pagesTo}`, true)}
        {askRow('', buttons(d.buttons))}
        {kitStale(loadedKit, d.kit) && (
          <Box flexDirection="row">
            {cell(2, text('›', false, 'warning'))}
            {rest(text(KIT_STALE, false, 'warning'))}
          </Box>
        )}
        {d.attention.map(a => (
          <Box flexDirection="row">
            {cell(2, text(a.level === 'act' ? '›' : '·', a.level !== 'act', a.level === 'act' ? 'warning' : undefined))}
            {rest(text(a.text, a.level !== 'act', a.level === 'act' ? 'warning' : undefined))}
          </Box>
        ))}

        {/* Input from outside this session, today boss mail: shown only while something is unread. */}
        {(d.mail?.count ?? 0) > 0 && (
          <Box flexDirection="column">
            {section('inbox', `${d.mail?.count} unread · boss-mail inbox`)}
            {(d.mail?.items ?? []).slice(0, INBOX_ROWS).map(m => (
              <Box flexDirection="row">
                {cell(10, text(m.kind, false, 'warning'))}
                {rest(text(`${m.from}: ${m.subject}`, false))}
              </Box>
            ))}
            {(d.mail?.count ?? 0) > INBOX_ROWS && text(`+${(d.mail?.count ?? 0) - INBOX_ROWS} more`, true)}
          </Box>
        )}

        {section('bosses', `${bosses.length} boss${bosses.length === 1 ? '' : 'es'}`)}
        {bosses.map(b => row(b))}

        {section('workers', `${active} active · ${items.length - active} idle`)}
        {items.map((it, i) => row(it, i < 9 ? i + 1 : undefined))}
        {stale.length > 0 && (
          <Box flexDirection="row" flexWrap="wrap">
            {text(`${stale.length} idle ${STALE_PR_DAYS}d+ `, true)}
            {stale.map(p => (
              <Button plain key={`stale-${p.num}`} onPress={() => void openUrl($, p.url)}>
                <Text dimColor color={p.ci === 'red' ? 'error' : undefined}>{`#${p.num} `}</Text>
              </Button>
            ))}
          </Box>
        )}
        {d.watchers
          .filter(w => w.stale)
          .map(w => text(`! watcher ${w.ws.slice(0, 8)} stale, ${ago(w.ageS)}`, false, 'error'))}

        {/* One quiet line when it fits: the tracker and the hint flow on the left, wrapping whole, the age stays right. */}
        <Box flexDirection="row" justifyContent="space-between" columnGap={2} marginTop={1}>
          <Box flexDirection="row" flexWrap="wrap" columnGap={2} flexShrink={1}>
            {[footer(d), 'press a row for details'].filter(Boolean).map(t => (
              <Box flexShrink={0}>
                <Text dimColor>{t}</Text>
              </Box>
            ))}
          </Box>
          <Box flexShrink={0}>
            <Text dimColor>{`${ago(now - d.at)} ago`}</Text>
          </Box>
        </Box>
      </Box>
    )
  })
}
