import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, test, expect, vi } from 'vitest'
import { Menu } from '@/components/ui/Menu'

function setup(overrides: Partial<Parameters<typeof Menu>[0]> = {}) {
  const onFirst = vi.fn()
  const onSecond = vi.fn()
  const onThird = vi.fn()
  render(
    <div>
      <button>outside</button>
      <Menu
        label="More"
        items={[
          { label: 'First', onSelect: onFirst },
          { label: 'Second', onSelect: onSecond, disabled: true },
          { label: 'Third', onSelect: onThird },
        ]}
        {...overrides}
      />
    </div>,
  )
  return { onFirst, onSecond, onThird, user: userEvent.setup() }
}

const trigger = () => screen.getByRole('button', { name: /more/i })

describe('Menu', () => {
  test('is closed by default and exposes menu semantics on the trigger', () => {
    setup()
    expect(screen.queryByRole('menu')).toBeNull()
    expect(trigger()).toHaveAttribute('aria-haspopup', 'menu')
    expect(trigger()).toHaveAttribute('aria-expanded', 'false')
  })

  test('clicking the trigger opens the menu and focuses the first enabled item', async () => {
    const { user } = setup()
    await user.click(trigger())
    expect(screen.getByRole('menu')).toBeInTheDocument()
    expect(trigger()).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('menuitem', { name: 'First' })).toHaveFocus()
  })

  test('clicking the trigger again closes the menu', async () => {
    const { user } = setup()
    await user.click(trigger())
    await user.click(trigger())
    expect(screen.queryByRole('menu')).toBeNull()
  })

  test('selecting an item calls its handler once and closes the menu', async () => {
    const { user, onFirst } = setup()
    await user.click(trigger())
    await user.click(screen.getByRole('menuitem', { name: 'First' }))
    expect(onFirst).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('menu')).toBeNull()
  })

  test('a disabled item is not selectable', async () => {
    const { user, onSecond } = setup()
    await user.click(trigger())
    const second = screen.getByRole('menuitem', { name: 'Second' })
    expect(second).toBeDisabled()
    await user.click(second)
    expect(onSecond).not.toHaveBeenCalled()
  })

  test('Escape closes the menu and returns focus to the trigger', async () => {
    const { user } = setup()
    await user.click(trigger())
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).toBeNull()
    expect(trigger()).toHaveFocus()
  })

  test('clicking outside closes the menu', async () => {
    const { user } = setup()
    await user.click(trigger())
    await user.click(screen.getByRole('button', { name: 'outside' }))
    expect(screen.queryByRole('menu')).toBeNull()
  })

  test('Tab closes the menu', async () => {
    const { user } = setup()
    await user.click(trigger())
    await user.keyboard('{Tab}')
    expect(screen.queryByRole('menu')).toBeNull()
  })

  test('ArrowDown/ArrowUp move between enabled items, skipping disabled ones and wrapping', async () => {
    const { user } = setup()
    await user.click(trigger())
    expect(screen.getByRole('menuitem', { name: 'First' })).toHaveFocus()
    await user.keyboard('{ArrowDown}')
    expect(screen.getByRole('menuitem', { name: 'Third' })).toHaveFocus()
    await user.keyboard('{ArrowDown}')
    expect(screen.getByRole('menuitem', { name: 'First' })).toHaveFocus()
    await user.keyboard('{ArrowUp}')
    expect(screen.getByRole('menuitem', { name: 'Third' })).toHaveFocus()
  })

  test('Home and End jump to the first and last enabled item', async () => {
    const { user } = setup()
    await user.click(trigger())
    await user.keyboard('{End}')
    expect(screen.getByRole('menuitem', { name: 'Third' })).toHaveFocus()
    await user.keyboard('{Home}')
    expect(screen.getByRole('menuitem', { name: 'First' })).toHaveFocus()
  })

  test('ArrowDown on the closed trigger opens the menu', async () => {
    const { user } = setup()
    trigger().focus()
    await user.keyboard('{ArrowDown}')
    expect(screen.getByRole('menu')).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'First' })).toHaveFocus()
  })

  test('Enter on the focused item selects it', async () => {
    const { user, onFirst } = setup()
    await user.click(trigger())
    await user.keyboard('{Enter}')
    expect(onFirst).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('menu')).toBeNull()
  })

  test('the menu is named after the trigger label', async () => {
    const { user } = setup()
    await user.click(trigger())
    expect(screen.getByRole('menu', { name: 'More' })).toBeInTheDocument()
  })
})
