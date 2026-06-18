import { render, screen } from '@testing-library/react'
import { ConnectionBadge } from '@/components/ConnectionBadge'
import { WsConnectionProvider } from '@/stores/wsConnection'
import { describe, test, expect } from 'vitest'

function wrap(ui: React.ReactElement) {
  return render(<WsConnectionProvider>{ui}</WsConnectionProvider>)
}

describe('ConnectionBadge', () => {
  test('renders nothing when state is idle', () => {
    const { container } = wrap(<ConnectionBadge />)
    expect(container.firstChild).toBeEmptyDOMElement()
  })
})
