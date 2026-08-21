import type { RssSubscriptionRead } from '@/types/api'
import { useSubscriptionPreview } from '@/hooks/useRss'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'

export function SubPreviewModal({ sub, onClose }: { sub: RssSubscriptionRead; onClose: () => void }) {
  const { data: composed, isLoading, isError } = useSubscriptionPreview(sub.id)

  return (
    <Modal onClose={onClose} tone="light" maxWidth="xl" className="flex flex-col max-h-[90vh]">
        <div className="flex items-center justify-between p-4 border-b">
          <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">Subscription Config Preview</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-xl leading-none">✕</button>
        </div>
        <div className="overflow-y-auto p-4">
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
            Composed output for <strong>{sub.name}</strong> (key: {sub.remote_key ?? 'unassigned'})
          </p>
          {isLoading && <p className="text-sm text-gray-500 dark:text-gray-400">Loading preview…</p>}
          {isError && <p className="text-sm text-red-600 dark:text-red-400">Failed to load preview.</p>}
          {composed && (
            <pre className="bg-gray-50 dark:bg-gray-900 border rounded p-3 text-xs font-mono whitespace-pre-wrap break-all">
              {JSON.stringify(composed, null, 2)}
            </pre>
          )}
        </div>
        <div className="flex justify-end p-4 border-t bg-gray-50 dark:bg-gray-900 rounded-b-lg">
          <Button onClick={onClose} variant="secondary" tone="light" size="md">Close</Button>
        </div>
    </Modal>
  )
}
