import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { WsConnectionProvider } from '@/stores/wsConnection'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { Layout } from '@/components/Layout'
import Dashboard from '@/pages/Dashboard'
import Shows from '@/pages/Shows'
import ShowDetail from '@/pages/ShowDetail'
import Files from '@/pages/Files'
import Watchlist from '@/pages/Watchlist'
import Tasks from '@/pages/Tasks'
import Settings from '@/pages/Settings'
import Data from '@/pages/Data'
import RSS from '@/pages/RSS'

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
      <WsConnectionProvider>
        <BrowserRouter>
          <ErrorBoundary>
            <Routes>
              <Route element={<Layout />}>
                <Route path="/" element={<Dashboard />} />
                <Route path="/shows" element={<Shows />} />
                <Route path="/shows/:id" element={<ShowDetail />} />
                <Route path="/files" element={<Files />} />
                <Route path="/watchlist" element={<Watchlist />} />
                <Route path="/tasks" element={<Tasks />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="/data" element={<Data />} />
                <Route path="/rss" element={<RSS />} />
              </Route>
            </Routes>
          </ErrorBoundary>
        </BrowserRouter>
      </WsConnectionProvider>
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  )
}
