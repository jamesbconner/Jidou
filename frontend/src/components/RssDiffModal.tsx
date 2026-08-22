import type { RssConfigDiff } from '@/types/api'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'

interface Props {
  diff: RssConfigDiff
  onClose: () => void
}

function diffLineClass(line: string): string {
  if (line.startsWith('+') && !line.startsWith('+++')) return 'text-green-400 bg-green-950/40'
  if (line.startsWith('-') && !line.startsWith('---')) return 'text-red-400 bg-red-950/40'
  if (line.startsWith('@@')) return 'text-indigo-400'
  return 'text-zinc-400'
}

/** Shows the unified diff between the current DB-composed config and the last snapshot Jidou saw. */
export function RssDiffModal({ diff, onClose }: Props) {
  return (
    <Modal onClose={onClose} tone="dark" maxWidth="2xl" labelledBy="rss-diff-title">
      <div className="px-5 py-4 border-b border-zinc-700 flex items-center justify-between">
        <div>
          <h2 id="rss-diff-title" className="text-sm font-semibold text-zinc-100">
            Changes since last upload
          </h2>
          <p className="text-xs text-zinc-400 mt-0.5">
            Snapshot #{diff.snapshot_id} ({diff.snapshot_type}) captured{' '}
            {new Date(diff.snapshot_created_at).toLocaleString()}
          </p>
        </div>
        <Button onClick={onClose} tone="dark" size="sm">
          Close
        </Button>
      </div>
      <div className="p-4 max-h-[70vh] overflow-auto">
        {diff.has_changes ? (
          <pre className="text-xs font-mono whitespace-pre-wrap">
            {diff.diff.map((line, i) => (
              <div key={i} className={diffLineClass(line)}>
                {line}
              </div>
            ))}
          </pre>
        ) : (
          <p className="text-sm text-zinc-400">
            No changes — the current configuration matches the last upload.
          </p>
        )}
      </div>
    </Modal>
  )
}
