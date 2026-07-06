import { useState, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Bar, BarChart, Cell, Pie, PieChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'
import { api } from '@/api/client'
import { useActiveTasks, useTask, useCancelTask } from '@/hooks/useTasks'
import { useTaskProgress } from '@/hooks/useTaskProgress'
import { TaskProgressBar } from '@/components/TaskProgressBar'
import { RecentShowsSection } from '@/components/RecentShowsSection'
import { RecentEpisodesSection } from '@/components/RecentEpisodesSection'
import { MediaDetailModal } from '@/components/MediaDetailModal'
import type { RecentSort } from '@/hooks/useDashboard'
import type {
  AdminStats,
  FileTimelineEntry,
  PipelineStatusEntry,
  RecentShowItem,
  RecentEpisodeItem,
} from '@/types/api'

type ModalItem =
  | { kind: 'show'; show: RecentShowItem; sort: RecentSort }
  | { kind: 'episode'; episode: RecentEpisodeItem; sort: RecentSort }

// Colours for the pipeline status donut
const STATUS_COLOURS: Record<string, string> = {
  routed: '#22c55e',
  matched: '#3b82f6',
  routing: '#a855f7',
  downloaded: '#06b6d4',
  downloading: '#f59e0b',
  discovered: '#94a3b8',
  unmatched: '#f97316',
  error: '#ef4444',
  pending: '#d1d5db',
}

function LiveTask({ taskId }: { taskId: number }) {
  const { data: task } = useTask(taskId)
  useTaskProgress(task?.celery_task_id ?? null)
  return null
}

interface StatCardProps {
  label: string
  value: string | number
  sub?: string
  tooltip: string
  alert?: boolean
}

function StatCard({ label, value, sub, tooltip, alert = false }: StatCardProps) {
  return (
    <div
      title={tooltip}
      className={`rounded-lg shadow p-4 cursor-default ${alert ? 'bg-red-50 border border-red-200' : 'bg-white'}`}
    >
      <p className="text-sm text-gray-500">{label}</p>
      <p className={`text-2xl font-bold ${alert ? 'text-red-600' : ''}`}>{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
    </div>
  )
}

export default function Dashboard() {
  const { data: activeTasks = [] } = useActiveTasks()
  const cancelTask = useCancelTask()
  const [modalItem, setModalItem] = useState<ModalItem | null>(null)
  // Stable across re-renders so RecentShowsSection/RecentEpisodesSection can
  // safely memoize their card lists on it without invalidating on every
  // unrelated parent re-render (dashboard polling, sibling state updates).
  const openShowModal = useCallback(
    (show: RecentShowItem, sort: RecentSort) => setModalItem({ kind: 'show', show, sort }),
    [],
  )
  const openEpisodeModal = useCallback(
    (episode: RecentEpisodeItem, sort: RecentSort) =>
      setModalItem({ kind: 'episode', episode, sort }),
    [],
  )

  const { data: stats } = useQuery({
    queryKey: ['admin', 'stats'],
    queryFn: () => api.get<AdminStats>('/admin/stats'),
    refetchInterval: 30_000,
  })

  const { data: timeline = [] } = useQuery({
    queryKey: ['admin', 'stats', 'files-timeline'],
    queryFn: () => api.get<FileTimelineEntry[]>('/admin/stats/files-timeline'),
    refetchInterval: 60_000,
  })

  const { data: pipelineStatus = [] } = useQuery({
    queryKey: ['admin', 'stats', 'pipeline-status'],
    queryFn: () => api.get<PipelineStatusEntry[]>('/admin/stats/pipeline-status'),
    refetchInterval: 30_000,
  })

  // Fill missing days in the timeline with 0 so bars are evenly spaced
  const timelineData = (() => {
    const byDate = Object.fromEntries(timeline.map((e) => [e.date, e.count]))
    const days: FileTimelineEntry[] = []
    for (let i = 29; i >= 0; i--) {
      const d = new Date()
      d.setUTCDate(d.getUTCDate() - i)
      const key = d.toISOString().slice(0, 10)
      days.push({ date: key.slice(5), count: byDate[key] ?? 0 })
    }
    return days
  })()

  return (
    <div className="space-y-6">
      {activeTasks.map((t) => <LiveTask key={t.id} taskId={t.id} />)}

      <h1 className="text-2xl font-bold">Dashboard</h1>

      {/* Stat cards */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
          <StatCard
            label="Shows in Library"
            value={stats.shows}
            tooltip="Total number of shows tracked in the local database."
          />
          <StatCard
            label="Episodes Tracked"
            value={stats.episodes_tracked}
            sub={`of ${stats.episodes_total} synced from TMDB · ${stats.episodes_total - stats.episodes_tracked} missing`}
            tooltip="Episodes with a local file tracked. 'Missing' is the gap between TMDB metadata and tracked files — import unmatched files contribute to this count."
          />
          <StatCard
            label="Newly Tracked"
            value={stats.files_added_1d}
            sub={`${stats.files_added_7d} past 7d · ${stats.files_added_30d} past 30d`}
            tooltip="Episodes newly marked as tracked in the past 1 day (header), 7 days, and 30 days. Counts both SFTP-routed files and path imports."
          />
          <StatCard
            label="Files Need Attention"
            value={stats.files_needs_attention}
            sub="unmatched or errored"
            tooltip="Files in 'unmatched' or 'error' status that require manual review or re-processing."
            alert={stats.files_needs_attention > 0}
          />
          <StatCard
            label="Shows Need Attention"
            value={stats.dq_total}
            sub={[
              stats.dq_no_path > 0 && `${stats.dq_no_path} no path`,
              stats.dq_no_content_type > 0 && `${stats.dq_no_content_type} no type`,
              stats.dq_no_episodes > 0 && `${stats.dq_no_episodes} no episodes`,
            ].filter(Boolean).join(' · ') || 'all clear'}
            tooltip="Shows with data quality issues: missing local path, unset content type, or episodes not yet synced. See Shows → Data Quality for details."
            alert={stats.dq_total > 0}
          />
        </div>
      )}

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Files added — bar chart */}
        <div className="bg-white rounded-lg shadow p-4">
          <h2 className="text-sm font-medium text-gray-700 mb-3">Episodes Tracked (past 30 days)</h2>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={timelineData} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
              <XAxis
                dataKey="date"
                tick={{ fontSize: 10 }}
                interval={6}
                tickLine={false}
                axisLine={false}
              />
              <YAxis allowDecimals={false} tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
              <Tooltip
                contentStyle={{ fontSize: 12 }}
                formatter={(v) => [v, 'Files']}
              />
              <Bar dataKey="count" fill="#3b82f6" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Pipeline status — donut */}
        <div className="bg-white rounded-lg shadow p-4">
          <h2 className="text-sm font-medium text-gray-700 mb-3">Pipeline Status</h2>
          {pipelineStatus.length === 0 ? (
            <p className="text-sm text-gray-400 mt-12 text-center">No files in the system yet.</p>
          ) : (
            <div className="flex items-center gap-4">
              <ResponsiveContainer width="50%" height={180}>
                <PieChart>
                  <Pie
                    data={pipelineStatus}
                    dataKey="count"
                    nameKey="status"
                    innerRadius={50}
                    outerRadius={80}
                    paddingAngle={2}
                  >
                    {pipelineStatus.map((entry) => (
                      <Cell key={entry.status} fill={STATUS_COLOURS[entry.status] ?? '#94a3b8'} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ fontSize: 12 }}
                    formatter={(v, name) => [v, name]}
                  />
                </PieChart>
              </ResponsiveContainer>
              <ul className="text-xs space-y-1.5 flex-1">
                {pipelineStatus.map((entry) => (
                  <li key={entry.status} className="flex items-center gap-2">
                    <span
                      className="inline-block w-2.5 h-2.5 rounded-full shrink-0"
                      style={{ background: STATUS_COLOURS[entry.status] ?? '#94a3b8' }}
                    />
                    <span className="capitalize text-gray-600 flex-1">{entry.status}</span>
                    <span className="font-medium text-gray-800">{entry.count}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      {/* Recently added carousels */}
      <RecentShowsSection onCardClick={openShowModal} />
      <RecentEpisodesSection onCardClick={openEpisodeModal} />

      {/* Active tasks */}
      <section>
        <h2 className="text-lg font-semibold mb-3">Active Tasks</h2>
        {activeTasks.length === 0 ? (
          <p className="text-gray-500 text-sm">No active tasks.</p>
        ) : (
          <div className="space-y-3">
            {activeTasks.map((t) => (
              <div key={t.id} className="bg-white rounded-lg shadow p-4">
                <TaskProgressBar task={t} onCancel={() => cancelTask.mutate(t.id)} />
              </div>
            ))}
          </div>
        )}
      </section>

      {modalItem && <MediaDetailModal item={modalItem} onClose={() => setModalItem(null)} />}
    </div>
  )
}
