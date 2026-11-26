import type { ExpertUser } from '@/lib/api'

const TOKEN_KEY = 'event_platform_jwt'
const EXPERT_KEY = 'event_platform_expert'

export function getAuthToken(): string | null {
  if (typeof window === 'undefined') return null
  return window.localStorage.getItem(TOKEN_KEY)
}

export function getStoredExpert(): ExpertUser | null {
  if (typeof window === 'undefined') return null
  const raw = window.localStorage.getItem(EXPERT_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as ExpertUser
  } catch {
    return null
  }
}

export function setAuthSession(token: string, expert: ExpertUser): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(TOKEN_KEY, token)
  window.localStorage.setItem(EXPERT_KEY, JSON.stringify(expert))
}

export function clearAuthSession(): void {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(TOKEN_KEY)
  window.localStorage.removeItem(EXPERT_KEY)
}
