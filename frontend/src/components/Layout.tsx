import { Outlet } from 'react-router-dom'
import { NavBar } from './NavBar'

export function Layout() {
  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <NavBar />
      <main className="flex-1 container mx-auto px-6 py-8 max-w-6xl">
        <Outlet />
      </main>
    </div>
  )
}
