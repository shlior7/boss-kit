import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Boss, Deck, Detail, Pr, ProofLink, Worker } from '../types'
import { ago, bossDetails, bossRow, footer, isActive, isBoss, mailContext, prDetails, prRow, rank, workerDetails, workerRow } from './details'
import type { PrView, Row } from './details'

const PANE = 'boss-deck'
const TITLE = 'Boss'
// The kit root: $BOSS_KIT_HOME, else ~/.claude/boss-kit. A shell expands it so the mod needs no env access.
const DATA_CMD = ['sh', '-c', 'exec python3 "${BOSS_KIT_HOME:-$HOME/.claude/boss-kit}/bin/boss-deck-data.py" "$@"', 'boss-deck-data']
const REFRESH_MS = 60_000
// A PR untouched this long folds into one 'stale' line.
const STALE_PR_DAYS = 10
// Unread messages listed in the inbox before it folds the rest into "+N more".
const INBOX_ROWS = 5
// Change a tag when its value's fields change: it declines what an earlier version stored.
const deck = atom({ plugin: 'boss-deck', key: 'deck' } as const, null, { shape: 'deck-9' })
const peek = atom({ plugin: 'boss-deck', key: 'peek' } as const, null, { shape: 'peek-4' })

// Quiet by design: grey text, color only where it means something: stage marks and what needs attention.

async function refresh($: EngineInterface, sessionStart = false, skipCache = false) {
  // The session's own workspace and directory, so the script resolves the boss the session's shell does.
  const ws = await $.env.get('SUPERSET_WORKSPACE_ID')
  const argv = [...DATA_CMD, '--cwd', await $.session.cwd(), ...(ws ? ['--workspace', ws] : []), ...(sessionStart ? ['--session-start'] : []), ...(skipCache ? ['--fresh'] : [])]
  const { exitCode, stdout, stderr } = await $.process.run(argv, { timeoutMs: 90_000 })
  const at = Math.floor((await $.clock.now()) / 1000)
  const fresh: Deck =
    exitCode === 0
      ? JSON.parse(stdout)
      : { at, next: '', attention: [], workers: [], watchers: [], prs: [], board: {}, error: stderr.slice(0, 200) }
  await update($, deck, () => fresh)
}

async function openUrl($: EngineInterface, url: string) {
  await $.process.run(['open', url], { timeoutMs: 10_000 })
}

async function openWorkspace($: EngineInterface, id: string) {
  await $.process.run(['superset', 'workspaces', 'open', id, '--local'], { timeoutMs: 20_000 })
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
  const [read, pr] = await Promise.all([
    w.id && w.term
      ? $.process.run(['superset', 'terminals', 'read', '--workspace', w.id, '--terminal', w.term, '--max-lines', '400', '--json'], { timeoutMs: 20_000 })
      : undefined,
    w.pr ? prView($, w.pr).catch(() => [{ label: 'pr', value: 'could not load', color: 'error' }]) : [],
  ])
  let screen = ''
  try {
    screen = JSON.parse(read?.stdout ?? '').text ?? ''
  } catch {}
  const links = [...w.proof, ...(w.pr?.proof ?? [])].filter((l, i, all) => all.findIndex(m => m.url === l.url) === i)
  return { rows: workerDetails(w, screen, pr), links }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const local = await $.fs.read('CLAUDE.local.md').catch(() => '')
    // A copy of the boss's CLAUDE.local.md, or another workspace on its checkout, stays quiet: no pane, no heartbeat.
    if (!isBoss(local, await $.env.get('SUPERSET_WORKSPACE_ID'))) return next(e)

    await $.command.register({ name: 'boss-deck', description: 'Open the boss pane and refresh it now' })
    void $.ui.open({ id: PANE, title: TITLE })
    void refresh($, true)
    $.clock.every(REFRESH_MS, () => void refresh($))

    return next(e)
  })

  on('command.run', { command: 'boss-deck' }, async $ => {
    await $.ui.open({ id: PANE, title: TITLE })
    await refresh($)

    return { text: 'Boss pane refreshed.' }
  })

  // While boss mail is unread, every prompt carries one context line naming it (never shown to the user).
  on('prompt.submit', async ($, e, next) => {
    if (e.command || e.isMeta) return next(e)
    const note = await unreadMail($)
    return next(note ? { ...e, context: [...(e.context ?? []), note] } : e)
  })

  // Refresh right after the boss dispatches, merges or comments, not only on the timer.
  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const ran = await next(e)
    if (/superset (terminals send|agents create)|gh pr (merge|edit|comment)|boss-sync/.test(e.command)) void refresh($, false, true)

    return ran
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const d = await read($, deck)
    if (!d) return <Text dimColor>loading…</Text>
    const shown = await read($, peek)
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
    type Open = { key: string; label: string; press: () => void }
    // The expanded row's ways out (proof, the workspace, GitHub) share one line, wrapping only when the pane is too narrow.
    const details = (rows: Detail[], links: ProofLink[], opens: Open[]) => (
      <Box flexDirection="column" paddingLeft={4} marginBottom={1}>
        {rows.map(r => (
          <Box flexDirection="row">
            {cell(9, text(r.label, true))}
            {rest(text(r.value, !r.color, r.color))}
          </Box>
        ))}
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
    type Item = { key: string; row: Row; load: () => Promise<{ rows: Detail[]; links?: ProofLink[] }>; opens: Open[] }
    const items: Item[] = [
      ...workers.map(w => ({ key: `w-${w.ws}`, row: workerRow(w, now), load: () => workerPeek($, w), opens: [...openWs(w.id), ...openGh(w.pr?.url)] })),
      ...loose
        .filter(p => !isStale(p))
        .map(p => ({ key: `p-${p.repo}-${p.num}`, row: prRow(p, now), load: async () => ({ rows: await prView($, p), links: p.proof }), opens: openGh(p.url) })),
    ]
    const bosses: Item[] = (d.bosses ?? []).map((b: Boss) => ({
      key: `b-${b.id}`, row: bossRow(b, now), load: async () => ({ rows: bossDetails(b, now) }), opens: openWs(b.workspace),
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
          {open && shown && details(shown.rows, shown.links ?? [], it.opens)}
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
