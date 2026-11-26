'use client'

import Link from 'next/link'
import { useCallback, useEffect, useState } from 'react'
import { Loader2, Plus, RefreshCw } from 'lucide-react'
import { useAuth } from '@/components/auth/auth-guard'
import { EventsList } from '@/components/dashboard/events-list'
import { StatsCards } from '@/components/dashboard/stats-cards'
import { PageHeader } from '@/components/layout/page-header'
import { Button } from '@/components/ui/button'
import { listMyEvents, type EventItem } from '@/lib/api'

export function DashboardClient() {
  const { token } = useAuth()
  const [events, setEvents] = useState<EventItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadEvents = useCallback(async () => {
    if (!token) return
    try {
      setError(null)
      const data = await listMyEvents(token)
      setEvents(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось загрузить мероприятия')
    } finally {
      setIsLoading(false)
    }
  }, [token])

  useEffect(() => {
    loadEvents()
  }, [loadEvents])

  return (
    <>
      <PageHeader
        title="Мои мероприятия"
        actions={
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={loadEvents}
              disabled={isLoading}
              className="h-9 gap-1.5 px-3"
            >
              <RefreshCw aria-hidden="true" className={`size-3.5 ${isLoading ? 'animate-spin' : ''}`} />
              Обновить
            </Button>
            <Button render={<Link href="/new" />} nativeButton={false} className="h-9 px-3">
              <Plus aria-hidden="true" />
              Создать мероприятие
            </Button>
          </div>
        }
      />

      <StatsCards events={events} />

      {isLoading ? (
        <div className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
          <Loader2 aria-hidden="true" className="size-4 animate-spin" />
          Загружаем мероприятия…
        </div>
      ) : error ? (
        <div role="alert" className="rounded-xl border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          {error}
        </div>
      ) : (
        <EventsList events={events} onRefresh={loadEvents} />
      )}
    </>
  )
}
