import { createContext, useContext, useLayoutEffect, type ReactNode } from 'react'
import { useLocalStorageState } from '@/hooks/useLocalStorage'

export type ColorScheme = 'light' | 'dark'

interface ThemeContextValue {
  colorScheme: ColorScheme
  setColorScheme: (scheme: ColorScheme) => void
  toggleColorScheme: () => void
}

const ThemeContext = createContext<ThemeContextValue>({
  colorScheme: 'light',
  setColorScheme: () => {},
  toggleColorScheme: () => {},
})

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [colorScheme, setColorScheme] = useLocalStorageState<ColorScheme>('jidou.colorScheme', 'light')

  // useLayoutEffect (not useEffect) so the `dark` class and `color-scheme`
  // land before the browser paints — otherwise consumers that read
  // `colorScheme` directly (e.g. Dashboard's Recharts theming) re-render one
  // frame before the CSS `dark:` variant activates, causing a visible flash
  // on every toggle.
  useLayoutEffect(() => {
    document.documentElement.classList.toggle('dark', colorScheme === 'dark')
    document.documentElement.style.colorScheme = colorScheme
  }, [colorScheme])

  function toggleColorScheme() {
    setColorScheme(colorScheme === 'dark' ? 'light' : 'dark')
  }

  return (
    <ThemeContext.Provider value={{ colorScheme, setColorScheme, toggleColorScheme }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useColorScheme() {
  return useContext(ThemeContext)
}
