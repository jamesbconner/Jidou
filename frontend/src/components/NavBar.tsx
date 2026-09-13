import { NavLink } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { ConnectionBadge } from './ConnectionBadge'
import { ThemeToggle } from './ui/ThemeToggle'
import { useAppSettings } from '@/hooks/useSettings'
import clsx from 'clsx'
import type { AppConfig } from '@/types/api'

type NavItem = { to: string; label: string; end?: boolean }

const BASE_LINKS: NavItem[] = [
  { to: '/shows', label: 'Shows' },
  { to: '/files', label: 'Files' },
  { to: '/watchlist', label: 'Watchlist' },
  { to: '/tasks', label: 'Tasks' },
  { to: '/settings', label: 'Settings' },
]

export function NavBar() {
  const { data: config } = useQuery({
    queryKey: ['config'],
    queryFn: () => api.get<AppConfig>('/config'),
    staleTime: 60_000,
  })
  const { data: appSettings } = useAppSettings()

  let links: NavItem[] = []
  if (appSettings?.dashboard_page_enabled ?? true) {
    links = [...links, { to: '/dashboard', label: 'Dashboard' }]
  }
  links = [...links, ...BASE_LINKS.slice(0, 1)]
  if (appSettings?.discover_enabled ?? true) {
    links = [...links, { to: '/discover', label: 'Discover' }]
  }
  links = [...links, ...BASE_LINKS.slice(1, 3)]
  if (appSettings?.calendar_enabled ?? true) {
    links = [...links, { to: '/calendar', label: 'Calendar' }]
  }
  if (config?.rss_config_path_set) {
    links = [...links, { to: '/rss', label: 'RSS' }]
  }
  links = [...links, ...BASE_LINKS.slice(3)]

  return (
    <nav className="sticky top-0 z-40 bg-gray-900 dark:bg-gray-950 text-white px-6 py-3 flex items-center gap-6">
      <span className="flex items-center gap-2 font-bold text-lg tracking-tight">
        <img src="/logo.svg" alt="" className="h-7 w-7" />
        Jidou
      </span>
      <div className="flex gap-4 flex-1">
        {links.map(({ to, label, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              clsx('text-sm transition-colors', isActive ? 'text-white font-medium' : 'text-gray-400 hover:text-white')
            }
          >
            {label}
          </NavLink>
        ))}
      </div>
      <ConnectionBadge />
      <div className="flex items-center gap-2">
        <ThemeToggle />
        <a
          href="https://github.com/jamesbconner/Jidou"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="View Jidou on GitHub"
          className="rounded p-1.5 text-gray-400 hover:text-white hover:bg-gray-800 dark:hover:bg-gray-700 transition-colors"
        >
          <svg viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4">
            <path d="M12 .5C5.73.5.98 5.24.98 11.52c0 5.02 3.26 9.28 7.77 10.78.57.1.78-.25.78-.55 0-.27-.01-1.16-.02-2.1-3.16.69-3.83-1.34-3.83-1.34-.52-1.32-1.26-1.67-1.26-1.67-1.03-.7.08-.69.08-.69 1.14.08 1.74 1.17 1.74 1.17 1.01 1.73 2.65 1.23 3.3.94.1-.73.4-1.23.72-1.51-2.52-.29-5.17-1.26-5.17-5.6 0-1.24.44-2.25 1.17-3.04-.12-.29-.51-1.45.11-3.02 0 0 .96-.31 3.14 1.16a10.9 10.9 0 015.72 0c2.18-1.47 3.14-1.16 3.14-1.16.62 1.57.23 2.73.11 3.02.73.79 1.17 1.8 1.17 3.04 0 4.35-2.65 5.31-5.18 5.59.41.35.77 1.04.77 2.1 0 1.52-.01 2.74-.01 3.11 0 .3.2.66.79.55 4.5-1.5 7.76-5.76 7.76-10.78C23.02 5.24 18.27.5 12 .5z" />
          </svg>
        </a>
      </div>
    </nav>
  )
}
