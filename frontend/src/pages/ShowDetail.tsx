import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useShow, useShowEpisodes, useUpdateShowPaths } from '@/hooks/useShows'
import { useTriggerTask } from '@/hooks/useTasks'

export default function ShowDetail() {
  const { id } = useParams<{ id: string }>()
  const showId = Number(id)

  const { data: show, isLoading } = useShow(showId)
  const { data: episodes = [] } = useShowEpisodes(showId)
  const updatePaths = useUpdateShowPaths(showId)
  const triggerTask = useTriggerTask()

  const [remotePath, setRemotePath] = useState('')
  const [localPath, setLocalPath] = useState('')
  const [pathsInit, setPathsInit] = useState(false)

  if (show && !pathsInit) {
    setRemotePath(show.remote_path ?? '')
    setLocalPath(show.local_path ?? '')
    setPathsInit(true)
  }

  if (isLoading) return <p className="text-gray-400">Loading…</p>
  if (!show) return <p className="text-red-500">Show not found.</p>

  const bySeason: Record<number, typeof episodes> = {}
  for (const ep of episodes) {
    ;(bySeason[ep.season_number] ??= []).push(ep)
  }

  function savePaths(e: React.FormEvent) {
    e.preventDefault()
    updatePaths.mutate({
      ...(remotePath !== (show?.remote_path ?? '') && { remote_path: remotePath || null }),
      ...(localPath !== (show?.local_path ?? '') && { local_path: localPath || null }),
    })
  }

  function triggerDownload(dryRun: boolean) {
    triggerTask.mutate({ task_type: 'download', show_id: showId, dry_run: dryRun })
  }

  const TMDB_IMG = 'https://image.tmdb.org/t/p/w500'

  return (
    <div className="space-y-8">
      <Link to="/shows" className="text-sm text-blue-600 hover:underline">← Back to Shows</Link>

      <div className="flex gap-6">
        {show.backdrop_path && (
          <img
            src={`${TMDB_IMG}${show.backdrop_path}`}
            alt={show.title}
            className="w-48 rounded-lg object-cover hidden md:block"
          />
        )}
        <div>
          <h1 className="text-2xl font-bold">{show.title}</h1>
          <p className="text-gray-500 text-sm mt-1">
            {show.release_date?.slice(0, 4)} · {show.media_type}
            {show.vote_average != null && ` · ★ ${show.vote_average.toFixed(1)}`}
          </p>
          {show.overview && <p className="text-sm text-gray-600 mt-2 max-w-xl">{show.overview}</p>}
        </div>
      </div>

      <section className="bg-white rounded-lg shadow p-4">
        <h2 className="font-semibold mb-3">Paths</h2>
        <form onSubmit={savePaths} className="space-y-3">
          <div>
            <label className="text-xs text-gray-500 block mb-1">Remote path (SFTP)</label>
            <input
              value={remotePath}
              onChange={(e) => setRemotePath(e.target.value)}
              className="border rounded px-2 py-1 text-sm w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="/shows/example"
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">Local path</label>
            <input
              value={localPath}
              onChange={(e) => setLocalPath(e.target.value)}
              className="border rounded px-2 py-1 text-sm w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="/media/example"
            />
          </div>
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={updatePaths.isPending}
              className="px-3 py-1 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
            >
              Save Paths
            </button>
          </div>
        </form>
      </section>

      <section className="bg-white rounded-lg shadow p-4">
        <h2 className="font-semibold mb-3">Actions</h2>
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={() => triggerDownload(false)}
            disabled={triggerTask.isPending}
            className="px-3 py-1 bg-green-600 text-white text-sm rounded hover:bg-green-700 disabled:opacity-50"
          >
            Download Files
          </button>
          <button
            onClick={() => triggerDownload(true)}
            disabled={triggerTask.isPending}
            className="px-3 py-1 bg-gray-200 text-gray-700 text-sm rounded hover:bg-gray-300 disabled:opacity-50"
          >
            Dry Run
          </button>
        </div>
      </section>

      <section>
        <h2 className="font-semibold mb-3">Episodes ({episodes.length})</h2>
        {Object.entries(bySeason)
          .sort(([a], [b]) => Number(a) - Number(b))
          .map(([season, eps]) => (
            <details key={season} className="mb-2">
              <summary className="cursor-pointer text-sm font-medium py-1">
                Season {season} ({eps.length} episodes)
              </summary>
              <div className="mt-2 divide-y border rounded-lg">
                {eps
                  .sort((a, b) => a.episode_number - b.episode_number)
                  .map((ep) => (
                    <div key={ep.id} className="flex items-center justify-between px-3 py-2 text-sm">
                      <span>
                        {ep.episode_number}. {ep.name}
                        {ep.air_date && <span className="text-gray-400 ml-2 text-xs">{ep.air_date}</span>}
                      </span>
                      {ep.file_tracked && (
                        <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">Tracked</span>
                      )}
                    </div>
                  ))}
              </div>
            </details>
          ))}
      </section>
    </div>
  )
}
