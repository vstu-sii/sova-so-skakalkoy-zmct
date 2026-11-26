'use client'

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { useRouter } from 'next/navigation'
import { Loader2 } from 'lucide-react'
import { ApiError, fetchCurrentExpert, type ExpertUser } from '@/lib/api'
import { clearAuthSession, getAuthToken, getStoredExpert, setAuthSession } from '@/lib/auth'

type AuthContextValue = {
  token: string | null
  expert: ExpertUser | null
  logout: () => void
}

const AuthContext = createContext<AuthContextValue>({
  token: null,
  expert: null,
  logout: () => {},
})

export function useAuth() {
  return useContext(AuthContext)
}

export function AuthGuard({ children }: { children: ReactNode }) {
  const router = useRouter()
  const [token, setToken] = useState<string | null>(null)
  const [expert, setExpert] = useState<ExpertUser | null>(null)
  const [ready, setReady] = useState(false)

  const logout = useCallback(() => {
    clearAuthSession()
    setToken(null)
    setExpert(null)
    router.replace('/login')
  }, [router])

  useEffect(() => {
    let cancelled = false
    const storedToken = getAuthToken()
    if (!storedToken) {
      router.replace('/login')
      return
    }

    const cachedExpert = getStoredExpert()
    setToken(storedToken)
    if (cachedExpert) setExpert(cachedExpert)

    fetchCurrentExpert(storedToken)
      .then((me) => {
        if (cancelled) return
        setExpert(me)
        setAuthSession(storedToken, me)
        setReady(true)
      })
      .catch((err) => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 401) {
          clearAuthSession()
          router.replace('/login')
          return
        }
        // Если бэкенд временно недоступен, но токен есть в localStorage — не выкидываем на login
        setReady(true)
      })

    return () => {
      cancelled = true
    }
  }, [router])

  if (!ready) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-background text-muted-foreground">
        <div className="flex items-center gap-2 text-sm">
          <Loader2 aria-hidden="true" className="size-4 animate-spin" />
          Проверяем авторизацию…
        </div>
      </div>
    )
  }

  return (
    <AuthContext.Provider value={{ token, expert, logout }}>
      {children}
    </AuthContext.Provider>
  )
}
