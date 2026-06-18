import { NavLink } from 'react-router-dom'
import { ConnectionBadge } from './ConnectionBadge'
import clsx from 'clsx'

const LINKS = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/shows', label: 'Shows' },
  { to: '/files', label: 'Files' },
  { to: '/tasks', label: 'Tasks' },
  { to: '/settings', label: 'Settings' },
]

export function NavBar() {
  return (
    <nav className="bg-gray-900 text-white px-6 py-3 flex items-center gap-6">
      <span className="font-bold text-lg tracking-tight">Jidou</span>
      <div className="flex gap-4 flex-1">
        {LINKS.map(({ to, label, end }) => (
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
