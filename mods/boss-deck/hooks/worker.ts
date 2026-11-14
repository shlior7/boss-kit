import type { SessionMessage } from 'claude-code'

import type { Live, Pr, Task, WorkerView } from '../types'
import { who } from './details'

type Part = { text: string; color?: string }

/** The session's task list as its own task-tool calls left it: TodoWrite replaces it, TaskCreate adds, TaskUpdate edits. */
export function taskList(msgs: readonly SessionMessage[]): Task[] {
  let tasks: Task[] = []
  for (const m of msgs) {
    for (const u of m.toolUses ?? []) {
      if (u.isError) continue
      const i = u.input as Record<string, any>
      if (u.tool === 'TodoWrite' && Array.isArray(i.todos)) {
        tasks = i.todos.map((t: any, n: number) => ({ id: String(n + 1), subject: String(t.content ?? ''), status: t.status, active: t.activeForm }))
      } else if (u.tool === 'TaskCreate') {
        const id = String((u.result as any)?.task?.id ?? tasks.length + 1)
        tasks = [...tasks, { id, subject: String(i.subject ?? ''), status: 'pending', active: i.activeForm }]
      } else if (u.tool === 'TaskUpdate') {
        const id = String(i.taskId)
        tasks = i.status === 'deleted'
          ? tasks.filter(t => t.id !== id)
          : tasks.map(t => (t.id === id ? { ...t, ...(i.status && { status: i.status }), ...(i.subject && { subject: i.subject }), ...(i.activeForm && { active: i.activeForm }) } : t))
      }
    }
  }
  return tasks
}

/** What .boss/status.json carries for the boss's row. */
export const progress = (tasks: Task[]) => {
  const cur = tasks.find(t => t.status === 'in_progress')
  return { tasks_done: tasks.filter(t => t.status === 'completed').length, tasks_total: tasks.length, current: cur?.active || cur?.subject || '' }
}

const BRIEF = ['command', 'description', 'file_path', 'pattern', 'url', 'subject', 'query', 'prompt']
/** The session's latest step: its newest tool call, "Bash(make test)", else one line of its newest assistant text. */
export function activity(msgs: readonly SessionMessage[]): string {
  for (let i = msgs.length - 1; i >= 0; i--) {
    const m = msgs[i]
    if (m?.role !== 'assistant') continue
    const u = m.toolUses.at(-1)
    if (u) {
      const arg = BRIEF.map(k => u.input[k]).find(v => typeof v === 'string' && v) as string | undefined
      return `${u.tool}(${(arg ?? '').split('\n')[0]?.slice(0, 60)})`
    }
    const line = m.text.split('\n').map(l => l.trim()).find(Boolean)
    if (line) return line
  }
  return ''
}

/** The messages a Bash command sends with `superset terminals send --text`: a key-only send (--keys) is no message. */
export function sentMessages(command: string): { ws: string; text: string }[] {
  return command.split(/\bsuperset\s+terminals\s+send\b/).slice(1).flatMap(seg => {
    const ws = /--workspace[=\s]+["']?([\w-]+)/.exec(seg)?.[1]
    const t = /--text[=\s]+(?:"((?:[^"\\]|\\.)*)"|'([^']*)'|(\S+))/.exec(seg)
    const text = (t?.[1]?.replace(/\\(.)/g, '$1') ?? t?.[2] ?? t?.[3] ?? '').replace(/\s+/g, ' ').trim().slice(0, 200)
    return ws && text ? [{ ws, text }] : []
  })
}

const CI_MARK = { green: ['✓', 'success'], red: ['✗', 'error'], pending: ['…', undefined] } as const
/** A worker's PR as one row: number, draft or ready, CI, mergeability, review. */
export function prParts(p: Pr): Part[] {
  const [mark, color] = CI_MARK[p.ci]
  return [
    { text: `#${p.num}` },
    { text: p.draft ? 'draft' : 'ready' },
    { text: `CI ${mark}`, color },
    { text: p.merge.toLowerCase(), color: p.merge === 'CONFLICTING' ? 'warning' : undefined },
    p.review === 'APPROVED' ? { text: 'approved', color: 'success' }
    : p.reviewers[0] ? { text: `→ ${who(p.reviewers[0])}` }
    : { text: p.review ? p.review.toLowerCase().replace('_', ' ') : 'no review' },
  ]
}

/** The state row: the agent's state, its stage and how long it has been there, then what it is doing now. */
export function stateParts(v: WorkerView, l: Live | null, ago: (s: number) => string, nowS: number): Part[] {
  const st = v.stage
  return [
    l?.busy ? { text: 'working', color: 'success' } : { text: 'idle' },
    { text: st ? `${st.stage} ${ago(Math.max(0, nowS - st.at))} ago` : '' },
    { text: l?.now ? `now: ${l.now}` : '' },
  ]
}

/** The warning line's parts, when any applies: context, a branch behind its base, red CI, idle without a DONE comment. */
export function workerWarnings(v: WorkerView, l: Live | null): string[] {
  const p = v.pr
  const done = !!p?.doneAt && p.doneAt >= v.sentAt
  return [
    (l?.ctx ?? 0) >= 60 ? `context ${l?.ctx}% · clear soon` : '',
    v.behind > 0 ? `${v.behind} behind origin/${v.base}` : '',
    p?.ci === 'red' ? 'CI red' : '',
    p && l && !l.busy && l.turnAt > 0 && !done ? 'idle, no DONE comment on the PR' : '',
  ].filter(Boolean)
}

/** How many of the boss's messages arrived since this session's last turn began. */
export const newMsgs = (v: WorkerView, l: Live | null) => v.msgs.filter(m => m.at * 1000 > (l?.turnAt ?? 0)).length
