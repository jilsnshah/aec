import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, useEffect, type ReactNode } from 'react'
import { ApiError, SIGNED_OUT } from '@/api/client'
import { api } from '@/api/endpoints'
import type { Me } from '@/api/types'

interface Auth {
  user: Me | null
  signOut: () => Promise<void>
}
const AuthContext = createContext<Auth>({ user: null, signOut: async () => undefined })
export const useAuth = () => useContext(AuthContext)

/** Shows the app to a signed-in user and the sign-in screen to anyone else.
 *  The session is an HttpOnly cookie; the app only asks who is signed in. */
export function AuthGate({ children, signIn }: { children: ReactNode; signIn: ReactNode }) {
  const client = useQueryClient()
  const me = useQuery({
    queryKey: ['me'],
    queryFn: async () => {
      try {
        return await api.auth.me()
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null
        throw error
      }
    },
    retry: false,
    staleTime: Infinity,
  })

  useEffect(() => {
    const onSignedOut = () => client.setQueryData(['me'], null)
    window.addEventListener(SIGNED_OUT, onSignedOut)
    return () => window.removeEventListener(SIGNED_OUT, onSignedOut)
  }, [client])

  async function signOut() {
    try {
      await api.auth.logout()
    } finally {
      client.setQueryData(['me'], null)
      // Drop everything the signed-in user could see, but keep the session
      // query itself so this gate notices the change.
      client.removeQueries({ predicate: (query) => query.queryKey[0] !== 'me' })
    }
  }

  if (me.isPending) return <div className="grid h-full place-items-center"><div className="size-8 animate-pulse rounded-xl bg-blue/80" /></div>
  if (!me.data) return <>{signIn}</>
  return <AuthContext.Provider value={{ user: me.data, signOut }}>{children}</AuthContext.Provider>
}
