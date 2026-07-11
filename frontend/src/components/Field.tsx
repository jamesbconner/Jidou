// Reusable modal field row — used by SubscriptionCreateModal and FeedFormModal.
export function Field({ label, note, children }: { label: string; note?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
      {children}
      {note && <p className="text-xs text-gray-400 mt-0.5">{note}</p>}
    </div>
  )
}
