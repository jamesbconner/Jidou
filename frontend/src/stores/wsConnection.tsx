import { createContext, useContext, useState, type ReactNode } from 'react'

type ConnState = 'connecting' | 'open' | 'closed' | 'idle'

interface WsConnectionContextValue {
  state: ConnState
  setState: (s: ConnState) => void
}

const WsConnectionContext = createContext<WsConnectionContextValue>({
  state: 'idle',
  setState: () => {},
})

export function WsConnectionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ConnState>('idle')
  return (
    <WsConnectionContext.Provider value={{ state, setState }}>
      {children}
    </WsConnectionContext.Provider>
  )
}

export function useWsConnectionState() {
  return useContext(WsConnectionContext)
}
