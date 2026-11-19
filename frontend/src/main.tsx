import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import * as Tooltip from '@radix-ui/react-tooltip'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { Toaster } from 'sonner'
import { App } from '@/app/App'
import { useTheme } from '@/app/theme'
import './styles/app.css'

const client = new QueryClient({
  defaultOptions: { queries: { staleTime: 15_000, refetchOnWindowFocus: true, retry: 1 } },
})

function ThemedToaster() {
  const { theme } = useTheme()
  return <Toaster position="bottom-right" theme={theme} toastOptions={{ className: '!bg-ink-750 !text-fg !border-white/10 !rounded-2xl !text-[13px] !font-sans' }} />
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Tooltip.Provider>
          <App />
          <ThemedToaster />
        </Tooltip.Provider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
