import { NavLink } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { ConnectionBadge } from './ConnectionBadge'
import clsx from 'clsx'
import type { AppConfig } from '@/types/api'

const BASE_LINKS = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/shows', label: 'Shows' },
  { to: '/files', label: 'Files' },
  { to: '/watchlist', label: 'Watchlist' },
  { to: '/calendar', label: 'Calendar' },
  { to: '/tasks', label: 'Tasks' },
  { to: '/data', label: 'Data' },
  { to: '/settings', label: 'Settings' },
]

export function NavBar() {
  const { data: config } = useQuery({
    queryKey: ['config'],
    queryFn: () => api.get<AppConfig>('/config'),
    staleTime: 60_000,
  })

  const links = config?.rss_config_path_set
    ? [...BASE_LINKS.slice(0, 5), { to: '/rss', label: 'RSS' }, ...BASE_LINKS.slice(5)]
    : BASE_LINKS

  return (
    <nav className="bg-gray-900 text-white px-6 py-3 flex items-center gap-6">
      <span className="font-bold text-lg tracking-tight">Jidou</span>
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
    </nav>
  )
}
