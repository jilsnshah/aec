import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { ApiError, SIGNED_OUT_EVENT, api } from '../api/client'

export interface SignedInUser {
  username: string
  is_admin: boolean
}

interface AuthState {
  user: SignedInUser | null
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthState>({ user: null, signOut: async () => undefined })

export function useAuth() {
  return useContext(AuthContext)
}

/** Shows the app to a signed-in user and the sign-in page to anyone else. The
 *  session lives in an HttpOnly cookie the browser sends; the app never sees it. */
export function AuthGate({ children, signIn }: { children: ReactNode; signIn: (done: (user: SignedInUser) => void) => ReactNode }) {
  const [user, setUser] = useState<SignedInUser | null>(null)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    api.auth
      .me()
      .then(setUser)
      .catch((cause) => {
        if (!(cause instanceof ApiError) || cause.status !== 401) console.error(cause)
        setUser(null)
      })
      .finally(() => setChecking(false))
    const signedOut = () => setUser(null)
    window.addEventListener(SIGNED_OUT_EVENT, signedOut)
    return () => window.removeEventListener(SIGNED_OUT_EVENT, signedOut)
  }, [])

  const signOut = useCallback(async () => {
    try {
      await api.auth.logout()
    } finally {
      setUser(null)
    }
  }, [])

  if (checking) return <div className="auth-loading" aria-busy="true" />
  if (!user) return <>{signIn(setUser)}</>
  return <AuthContext.Provider value={{ user, signOut }}>{children}</AuthContext.Provider>
}
