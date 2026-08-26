import { Suspense } from 'react'
import { Outlet } from 'react-router'
import { NavBar } from './NavBar'

export function Layout() {
  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950 flex flex-col">
      <NavBar />
      <main className="flex-1 container mx-auto px-6 py-8 max-w-6xl">
        <Suspense fallback={<p className="text-sm text-gray-400 dark:text-gray-500">Loading…</p>}>
          <Outlet />
        </Suspense>
      </main>
    </div>
  )
}
