import { useState } from 'react'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'

interface Props {
  title: string
  description: string
  confirmLabel?: string
  onConfirm: () => void
  onCancel: () => void
  danger?: boolean
}

export function ConfirmDialog({
  title,
  description,
  confirmLabel = 'Confirm',
  onConfirm,
  onCancel,
  danger = false,
}: Props) {
  const [fired, setFired] = useState(false)

  function handleConfirm() {
    if (fired) return
    setFired(true)
    onConfirm()
  }

  return (
    <Modal
      onClose={onCancel}
      tone="dark"
      maxWidth="sm"
      role="alertdialog"
      labelledBy="confirm-dialog-title"
      describedBy="confirm-dialog-desc"
    >
        <div className="px-5 py-4 space-y-2">
          <h2 id="confirm-dialog-title" className="text-sm font-semibold text-zinc-100">
            {title}
          </h2>
          <p id="confirm-dialog-desc" className="text-sm text-zinc-400">
            {description}
          </p>
        </div>
        <div className="px-5 py-3 border-t border-zinc-700 flex justify-end gap-2">
          <Button onClick={onCancel} disabled={fired} autoFocus variant="secondary" tone="dark" size="sm">
            Cancel
          </Button>
          <Button onClick={handleConfirm} disabled={fired} variant={danger ? 'danger' : 'primary'} tone="dark" size="sm">
            {confirmLabel}
          </Button>
        </div>
    </Modal>
  )
}
