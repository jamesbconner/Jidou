import { useColorScheme } from '@/stores/theme'

/**
 * Global light/dark mode switch. Rendered once in NavBar so it's reachable
 * from every route.
 */
export function ThemeToggle() {
  const { colorScheme, toggleColorScheme } = useColorScheme()
  const isDark = colorScheme === 'dark'

  return (
    <button
      type="button"
      onClick={toggleColorScheme}
      aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      aria-pressed={isDark}
      className="rounded p-1.5 text-gray-400 hover:text-white hover:bg-gray-800 dark:hover:bg-gray-700 transition-colors"
    >
      {isDark ? (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="w-4 h-4">
          <circle cx="12" cy="12" r="4" />
          <path
            strokeLinecap="round"
            d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"
          />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4">
          <path d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 1020.354 15.354z" />
        </svg>
      )}
    </button>
  )
}
