import { lazy } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { WsConnectionProvider } from '@/stores/wsConnection'
import { ThemeProvider } from '@/stores/theme'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { Layout } from '@/components/Layout'

// Lazy-loaded per route so each page ships in its own chunk instead of one
// bundle carrying all 10 pages regardless of which one is visited. Layout
// (nav bar + page frame) stays a static import since it's shared chrome that
// should never itself show a loading state -- see Layout.tsx's Suspense
// boundary around just the <Outlet />.
const Dashboard = lazy(() => import('@/pages/Dashboard'))
const Shows = lazy(() => import('@/pages/Shows'))
const Discover = lazy(() => import('@/pages/Discover'))
const ShowDetail = lazy(() => import('@/pages/ShowDetail'))
const Files = lazy(() => import('@/pages/Files'))
const Watchlist = lazy(() => import('@/pages/Watchlist'))
const Tasks = lazy(() => import('@/pages/Tasks'))
const Settings = lazy(() => import('@/pages/Settings'))
const RSS = lazy(() => import('@/pages/RSS'))
const Calendar = lazy(() => import('@/pages/Calendar'))

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <WsConnectionProvider>
          <BrowserRouter>
            <ErrorBoundary>
              <Routes>
                <Route element={<Layout />}>
                  <Route path="/" element={<Dashboard />} />
                  <Route path="/shows" element={<Shows />} />
                  <Route path="/discover" element={<Discover />} />
                  <Route path="/shows/:id" element={<ShowDetail />} />
                  <Route path="/files" element={<Files />} />
                  <Route path="/watchlist" element={<Watchlist />} />
                  <Route path="/calendar" element={<Calendar />} />
                  <Route path="/tasks" element={<Tasks />} />
                  <Route path="/settings" element={<Settings />} />
                  <Route path="/rss" element={<RSS />} />
                </Route>
              </Routes>
            </ErrorBoundary>
          </BrowserRouter>
        </WsConnectionProvider>
      </ThemeProvider>
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  )
}
