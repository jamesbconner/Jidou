import { useEffect, useRef } from 'react'
import clsx from 'clsx'
import type { TaskEvent } from '@/types/api'

interface Props {
  events: TaskEvent[]
  live?: boolean
}

const LEVEL_STYLES: Record<TaskEvent['level'], string> = {
  info: 'text-gray-500',
  warn: 'text-amber-600',
  error: 'text-red-600 font-medium',
}

const LEVEL_DOT: Record<TaskEvent['level'], string> = {
  info: 'bg-gray-400',
  warn: 'bg-amber-400',
  error: 'bg-red-500',
}

function formatTs(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return iso
  }
}

export function TaskEventLog({ events, live = false }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    // Scroll only the log container itself, not scrollIntoView() on a child,
    // which can cascade up through ancestor scrollables (including the page)
    // and yank the viewport down every time a new event arrives.
    const el = containerRef.current
    if (live && el) el.scrollTop = el.scrollHeight
  }, [events.length, live])

  if (events.length === 0) {
    return (
      <p className="text-xs text-gray-400 italic py-1">No events recorded yet.</p>
    )
  }

  return (
    <div ref={containerRef} className="max-h-64 overflow-y-auto text-xs font-mono space-y-0.5 pr-1">
      {events.map((ev, i) => (
        <div key={i} className="flex items-start gap-2">
          <span className="text-gray-400 shrink-0 tabular-nums">{formatTs(ev.ts)}</span>
          <span className={clsx('mt-1 w-1.5 h-1.5 rounded-full shrink-0', LEVEL_DOT[ev.level])} />
          <span className="break-words min-w-0">
            <span className={LEVEL_STYLES[ev.level]}>{ev.msg}</span>
            {typeof ev.ctx?.path === 'string' && (
              <span
                className="block text-gray-400 text-[10px] pl-0 truncate"
                title={ev.ctx.path}
              >
                {ev.ctx.path}
              </span>
            )}
          </span>
        </div>
      ))}
    </div>
  )
}
