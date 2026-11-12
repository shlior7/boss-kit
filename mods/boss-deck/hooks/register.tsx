import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Deck, Detail, Pr, ProofLink, Worker } from '../types'
import { footer, isBoss, mailContext, needsProof, prDetails, stack, workerDetails } from './details'
import type { PrView } from './details'

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
const deck = atom({ plugin: 'boss-deck', key: 'deck' } as const, null, { shape: 'deck-7' })
const peek = atom({ plugin: 'boss-deck', key: 'peek' } as const, null, { shape: 'peek-3' })

// Quiet by design: grey by default, color only for what needs attention.
const STATE_MARK: Record<string, string> = { working: '●', idle: '·', blocked: '■' }
const CI_MARK: Record<Pr['ci'], string> = { green: '✓', red: '✗', pending: '…' }

const ago = (s: number) => (s < 90 ? `${s}s` : s < 5400 ? `${Math.round(s / 60)}m` : `${Math.round(s / 3600)}h`)
// "JaneDoe42" -> "jane", "acme-reviewers" (a team) -> "team"
const who = (login: string) => (login.includes('-') ? 'team' : (login.match(/^[A-Z]?[a-z]+/)?.[0] ?? login).toLowerCase())
// Drops a conventional-commit prefix and a trailing #tag: "fix(api): x #team" -> "x".
const shortTitle = (t: string) => t.replace(/^\w+\([^)]*\): /, '').replace(/ #[\w-]+$/, '')
const prColor = (p: Pr) =>
  p.ci === 'red' ? 'error'
  : needsProof(p) ? 'warning'
  : p.draft ? 'subtle'
  : p.review === 'APPROVED' ? 'success'
  : p.merge === 'CONFLICTING' ? 'warning'
  : p.reviewers.length || p.review ? 'suggestion' : undefined
const prStatus = (p: Pr) =>
  needsProof(p) ? 'no proof'
  : p.draft ? 'draft'
  : p.review === 'APPROVED' ? 'approved'
  : p.merge === 'CONFLICTING' ? 'conflict'
  : p.reviewers.length ? `→ ${who(p.reviewers[0] ?? '')}`
  : p.review ? 'review' : ''

async function refresh($: EngineInterface, sessionStart = false) {
  // The session's own workspace and directory, so the script resolves the boss the session's shell does.
  const ws = await $.env.get('SUPERSET_WORKSPACE_ID')
  const argv = [...DATA_CMD, '--cwd', await $.session.cwd(), ...(ws ? ['--workspace', ws] : []), ...(sessionStart ? ['--session-start'] : [])]
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

/** Toggle one expanded row: a worker's or a PR's details under it. */
async function toggle(
  $: EngineInterface,
  key: string,
  load: () => Promise<{ rows: Detail[]; url?: string; links?: ProofLink[] }>,
) {
  const shown = await read($, peek)
  if (shown?.key === key) return update($, peek, () => null)
  await update($, peek, () => ({ key, rows: [{ label: '', value: 'loading…' }] }))
  const got = await load().catch(() => ({ rows: [{ label: 'error', value: 'could not load', color: 'error' }] }))
  // Closed, or another row opened, while this one loaded: keep what is shown now.
  await update($, peek, cur => (cur?.key === key ? { key, ...got } : cur))
}

async function workerPeek($: EngineInterface, w: Worker) {
  const { stdout } = await $.process.run(
    ['superset', 'terminals', 'read', '--workspace', w.id, '--terminal', w.term, '--max-lines', '400', '--json'],
    { timeoutMs: 20_000 },
  )
  let screen = ''
  try {
    screen = JSON.parse(stdout).text ?? ''
  } catch {}
  return { rows: workerDetails(w, screen), links: w.proof }
}

async function prPeek($: EngineInterface, p: Pr) {
  const fields = 'statusCheckRollup,mergeable,mergeStateStatus,additions,deletions,changedFiles,updatedAt,headRefOid,latestReviews,reviewRequests'
  const { stdout } = await $.process.run(['gh', 'pr', 'view', String(p.num), '--repo', p.repo, '--json', fields], { timeoutMs: 30_000 })
  const v: PrView = JSON.parse(stdout)
  return { rows: prDetails(p, v, Math.floor((await $.clock.now()) / 1000)), url: p.url, links: p.proof }
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
    if (/superset (terminals send|agents create)|gh pr (merge|edit|comment)|boss-sync/.test(e.command)) void refresh($)

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
    // `open` is the expanded row's way out: a PR's GitHub page, a worker's workspace.
    const details = (rows: Detail[], open?: { key: string; label: string; press: () => void }, links: ProofLink[] = []) => (
      <Box flexDirection="column" paddingLeft={4} marginBottom={1}>
        {rows.map(r => (
          <Box flexDirection="row">
            {cell(9, text(r.label, true))}
            {rest(text(r.value, !r.color, r.color))}
          </Box>
        ))}
        {/* Proof links and the way out share one line, wrapping only when the pane is too narrow. */}
        {(links.length > 0 || open) && (
          <Box flexDirection="row" columnGap={2} flexWrap="wrap">
            {links.map((l, i) => linkButton(`proof-${l.url}-${i}`, `${l.label} ↗`, l.url))}
            {open && (
              <Button plain key={open.key} onPress={open.press}>
                <Text color="suggestion">{open.label}</Text>
              </Button>
            )}
          </Box>
        )}
      </Box>
    )
    const working = d.workers.filter(w => w.state === 'working').length
    const cutoff = (now - STALE_PR_DAYS * 86400) * 1000
    const isStale = (p: Pr) => !!p.updated && Date.parse(p.updated) < cutoff
    const live = d.prs.filter(p => !isStale(p))
    const stale = d.prs.filter(isStale)

    const worker = (w: Worker, i: number) => {
      const dim = w.state !== 'working' && w.state !== 'blocked'
      const color = w.state === 'blocked' ? 'error' : undefined
      const key = `w-${w.ws}`
      const open = shown?.key === key
      return (
        <Box flexDirection="column">
          <Box flexDirection="row">
            {cell(2, text(STATE_MARK[w.state] ?? '○', dim, color))}
            {/* The whole row expands; the workspace opens from the details. A hotkey's "1: " takes 3 of the name's 23 cells. */}
            {rest(
              <Button plain key={`peek-${w.ws}`} hotkey={i < 9 ? String(i + 1) : undefined} onPress={() => void toggle($, key, () => workerPeek($, w))}>
                <Text dimColor={dim} color={color} bold={open}>
                  {w.name.slice(0, i < 9 ? 18 : 21).padEnd(i < 9 ? 20 : 23)}
                </Text>
                <Text dimColor={dim} color={color} wrap="truncate-end">
                  {w.task}
                </Text>
              </Button>,
            )}
          </Box>
          {open &&
            shown &&
            details(shown.rows, { key: `open-${w.ws}`, label: 'open workspace ↗', press: () => void openWorkspace($, w.id) }, shown.links)}
        </Box>
      )
    }

    const pr = ([p, depth]: [Pr, number]) => {
      const color = prColor(p)
      const tag = p.primary ? `#${p.num}` : `${p.tag ?? p.repo}#${p.num}`
      const key = `p-${p.repo}-${p.num}`
      return (
        <Box flexDirection="column">
          <Box flexDirection="row">
            {cell(2, text(CI_MARK[p.ci], p.ci !== 'red', p.ci === 'red' ? 'error' : undefined))}
            {depth > 0 && cell(2 * depth, text(`${' '.repeat(2 * depth - 2)}└`, true))}
            {cell(
              7,
              <Button plain key={key} onPress={() => void toggle($, key, () => prPeek($, p))}>
                <Text bold={shown?.key === key} wrap="truncate-end">
                  {tag}
                </Text>
              </Button>,
            )}
            {cell(11, text(prStatus(p), !color, color))}
            {rest(text(shortTitle(p.title), true))}
          </Box>
          {shown?.key === key &&
            details(shown.rows, shown.url ? { key: `gh-${shown.url}`, label: 'open on GitHub ↗', press: () => void openUrl($, shown.url ?? '') } : undefined, shown.links)}
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

        {section('workers', `${working} working · ${d.watchers.length} watched`)}
        {d.workers.length === 0 && text('none', true)}
        {d.workers.map(worker)}
        {d.watchers
          .filter(w => w.stale)
          .map(w => text(`! watcher ${w.ws.slice(0, 8)} stale, ${ago(w.ageS)}`, false, 'error'))}

        {section('pull requests', `${d.prs.filter(p => !p.draft).length} open · ${d.prs.filter(p => p.draft).length} draft`)}
        {stack(live).map(pr)}
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


        {/* One quiet line when it fits: the tracker and the hint flow on the left, wrapping whole, the age stays right. */}
        <Box flexDirection="row" justifyContent="space-between" columnGap={2} marginTop={1}>
          <Box flexDirection="row" flexWrap="wrap" columnGap={2} flexShrink={1}>
            {[footer(d), 'press a worker or a PR # for details'].filter(Boolean).map(t => (
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
