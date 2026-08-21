import { createContext, useContext, useEffect, type ReactNode } from 'react'
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

  useEffect(() => {
    document.documentElement.classList.toggle('dark', colorScheme === 'dark')
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
