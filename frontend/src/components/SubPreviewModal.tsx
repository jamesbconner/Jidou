import type { RssSubscriptionRead } from '@/types/api'
import { useSubscriptionPreview } from '@/hooks/useRss'

export function SubPreviewModal({ sub, onClose }: { sub: RssSubscriptionRead; onClose: () => void }) {
  const { data: composed, isLoading, isError } = useSubscriptionPreview(sub.id)

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-xl flex flex-col max-h-[90vh]">
        <div className="flex items-center justify-between p-4 border-b">
          <h2 className="text-base font-semibold text-gray-900">Subscription Config Preview</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">✕</button>
        </div>
        <div className="overflow-y-auto p-4">
          <p className="text-xs text-gray-500 mb-2">
            Composed output for <strong>{sub.name}</strong> (key: {sub.remote_key ?? 'unassigned'})
          </p>
          {isLoading && <p className="text-sm text-gray-500">Loading preview…</p>}
          {isError && <p className="text-sm text-red-600">Failed to load preview.</p>}
          {composed && (
            <pre className="bg-gray-50 border rounded p-3 text-xs font-mono whitespace-pre-wrap break-all">
              {JSON.stringify(composed, null, 2)}
            </pre>
          )}
        </div>
        <div className="flex justify-end p-4 border-t bg-gray-50 rounded-b-lg">
          <button onClick={onClose} className="px-4 py-1.5 text-sm rounded border border-gray-300 hover:bg-gray-100">Close</button>
        </div>
      </div>
    </div>
  )
}
