'use client'

import { use, useCallback, useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { EventHero } from '@/components/event/event-hero'
import {
  AboutSection,
  DatePlaceSection,
  ExpertSection,
  FinalCta,
  PriceSection,
} from '@/components/event/event-sections'
import { SubscribeModal } from '@/components/event/subscribe-modal'
import { publicEventFromApi } from '@/lib/adapters'
import { getPublicEventById } from '@/lib/api'
import type { PublicEvent } from '@/lib/public-event'

export default function PublicEventByIdPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = use(params)
  const [eventData, setEventData] = useState<PublicEvent | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showSubscribeModal, setShowSubscribeModal] = useState(false)

  const loadEvent = useCallback(async () => {
    try {
      setError(null)
      const apiData = await getPublicEventById(id)
      setEventData(publicEventFromApi(apiData))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Мероприятие не найдено')
    } finally {
      setIsLoading(false)
    }
  }, [id])

  useEffect(() => {
    loadEvent()
  }, [loadEvent])

  useEffect(() => {
    if (eventData) {
      document.title = `${eventData.title} — ${eventData.date}`
    }
  }, [eventData])

  if (isLoading) {
    return (
      <main className="flex min-h-dvh items-center justify-center px-5">
        <p role="status" className="flex items-center gap-2 text-muted-foreground">
          <Loader2 aria-hidden="true" className="size-4 animate-spin" />
          Загружаем страницу мероприятия…
        </p>
      </main>
    )
  }

  if (error || !eventData) {
    return (
      <main className="flex min-h-dvh items-center justify-center px-5">
        <p role="alert" className="text-destructive">
          {error ?? 'Не удалось загрузить мероприятие'}
        </p>
      </main>
    )
  }

  const openModal = () => setShowSubscribeModal(true)

  return (
    <main>
      <EventHero event={eventData} onSignup={openModal} />
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-14 px-5 py-14 sm:gap-16 sm:px-8 sm:py-20">
        <AboutSection event={eventData} />
        <DatePlaceSection event={eventData} />
        <PriceSection event={eventData} onSignup={openModal} />
        <ExpertSection event={eventData} />
        <FinalCta event={eventData} onSignup={openModal} />
      </div>

      {showSubscribeModal && (
        <SubscribeModal
          eventId={id}
          eventTitle={eventData.title}
          onClose={() => setShowSubscribeModal(false)}
          onSuccess={() => {
            setEventData((prev) =>
              prev
                ? {
                    ...prev,
                    subscribersCount: (prev.subscribersCount ?? 0) + 1,
                  }
                : prev,
            )
          }}
        />
      )}
    </main>
  )
}
