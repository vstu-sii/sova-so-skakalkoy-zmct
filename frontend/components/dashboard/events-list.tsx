'use client'

import Link from 'next/link'
import { useState } from 'react'
import { CalendarDays, ExternalLink, Loader2, Mail, MapPin, Plus, Send, Users, Wallet } from 'lucide-react'
import { StatusBadge } from '@/components/dashboard/status-badge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { formatEventDateTime, formatRubPrice } from '@/lib/adapters'
import { publishEventToVk, sendEventMailing, type EventItem } from '@/lib/api'
import type { EventStatus } from '@/lib/events'

type ActionFeedback = {
  type: 'success' | 'error'
  message: string
}

function normalizeStatus(status: string): EventStatus {
  if (status === 'published' || status === 'draft' || status === 'error') return status
  return 'draft'
}

export function EventsList({
  events,
  onRefresh,
}: {
  events: EventItem[]
  onRefresh: () => Promise<void>
}) {
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [feedbackByEvent, setFeedbackByEvent] = useState<Record<string, ActionFeedback>>({})

  async function handlePublishVk(eventId: string) {
    const key = `vk:${eventId}`
    if (busyAction) return
    setBusyAction(key)
    setFeedbackByEvent((prev) => {
      const next = { ...prev }
      delete next[eventId]
      return next
    })
    try {
      const res = await publishEventToVk(eventId)
      setFeedbackByEvent((prev) => ({
        ...prev,
        [eventId]: { type: 'success', message: res.message || 'Опубликовано в ВК' },
      }))
      await onRefresh()
    } catch (err) {
      setFeedbackByEvent((prev) => ({
        ...prev,
        [eventId]: {
          type: 'error',
          message: err instanceof Error ? err.message : 'Ошибка публикации в ВК',
        },
      }))
    } finally {
      setBusyAction(null)
    }
  }

  async function handleSendMailing(eventId: string) {
    const key = `mail:${eventId}`
    if (busyAction) return
    setBusyAction(key)
    setFeedbackByEvent((prev) => {
      const next = { ...prev }
      delete next[eventId]
      return next
    })
    try {
      const res = await sendEventMailing(eventId)
      setFeedbackByEvent((prev) => ({
        ...prev,
        [eventId]: { type: 'success', message: res.message },
      }))
      await onRefresh()
    } catch (err) {
      setFeedbackByEvent((prev) => ({
        ...prev,
        [eventId]: {
          type: 'error',
          message: err instanceof Error ? err.message : 'Ошибка рассылки',
        },
      }))
    } finally {
      setBusyAction(null)
    }
  }

  if (events.length === 0) {
    return (
      <section className="flex flex-col items-center gap-4 rounded-xl border border-dashed bg-card p-10 text-center">
        <div className="flex flex-col gap-1">
          <h2 className="text-base font-semibold text-foreground">Мероприятий пока нет</h2>
          <p className="text-sm text-muted-foreground">
            Создайте первый анонс — система извлечёт детали и создаст публичную страницу для записи участников.
          </p>
        </div>
        <Button render={<Link href="/new" />} nativeButton={false} className="gap-1.5">
          <Plus aria-hidden="true" className="size-4" />
          Создать мероприятие
        </Button>
      </section>
    )
  }

  return (
    <section aria-labelledby="events-heading" className="flex flex-col gap-3">
      <h2 id="events-heading" className="text-sm font-medium text-muted-foreground">
        Список мероприятий
      </h2>

      <ul className="flex flex-col gap-3">
        {events.map((event) => {
          const vkPub = event.publications.find((p) => p.channel === 'vk' && p.status === 'published')
          const emailPub = event.publications.find((p) => p.channel === 'email')
          const isVkBusy = busyAction === `vk:${event.id}`
          const isMailBusy = busyAction === `mail:${event.id}`
          const feedback = feedbackByEvent[event.id]

          return (
            <li
              key={event.id}
              className="flex flex-col gap-4 rounded-xl border bg-card p-4 text-card-foreground transition-colors hover:bg-accent/20 sm:p-5"
            >
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="flex flex-col gap-1.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-base font-semibold leading-snug text-pretty">{event.title}</h3>
                    <StatusBadge status={normalizeStatus(event.status)} />
                  </div>
                  <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-sm text-muted-foreground">
                    <span className="inline-flex items-center gap-1.5">
                      <CalendarDays className="size-4 shrink-0" aria-hidden="true" />
                      {formatEventDateTime(event.date)}
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <MapPin className="size-4 shrink-0" aria-hidden="true" />
                      {event.location || (event.is_online ? 'Онлайн' : 'Место не указано')}
                    </span>
                    <span className="inline-flex items-center gap-1.5 font-medium text-foreground tabular-nums">
                      <Wallet className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                      {formatRubPrice(event.price)}
                    </span>
                    <span className="inline-flex items-center gap-1.5 tabular-nums">
                      <Users className="size-4 shrink-0" aria-hidden="true" />
                      Записалось: {event.subscribers_count}
                    </span>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  {vkPub && (
                    <Badge variant="secondary" className="text-xs">
                      ВК: опубликовано
                    </Badge>
                  )}
                  {emailPub && (
                    <Badge variant="secondary" className="text-xs">
                      Рассылка: {emailPub.sent_count} писем
                    </Badge>
                  )}
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2 border-t pt-3">
                <Button
                  variant="outline"
                  size="sm"
                  render={<Link href={`/event/${event.id}`} />}
                  nativeButton={false}
                  className="gap-1.5"
                >
                  <ExternalLink aria-hidden="true" className="size-3.5" />
                  Открыть страницу
                </Button>

                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  disabled={busyAction !== null}
                  onClick={() => handlePublishVk(event.id)}
                  className="gap-1.5"
                >
                  {isVkBusy ? (
                    <Loader2 aria-hidden="true" className="size-3.5 animate-spin" />
                  ) : (
                    <Send aria-hidden="true" className="size-3.5" />
                  )}
                  {isVkBusy ? 'Публикуем…' : 'Опубликовать в ВК'}
                </Button>

                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  disabled={busyAction !== null}
                  onClick={() => handleSendMailing(event.id)}
                  className="gap-1.5"
                >
                  {isMailBusy ? (
                    <Loader2 aria-hidden="true" className="size-3.5 animate-spin" />
                  ) : (
                    <Mail aria-hidden="true" className="size-3.5" />
                  )}
                  {isMailBusy ? 'Отправляем…' : 'Сделать рассылку'}
                </Button>
              </div>

              {feedback && (
                <p
                  role={feedback.type === 'error' ? 'alert' : 'status'}
                  className={
                    feedback.type === 'error'
                      ? 'text-sm text-destructive'
                      : 'text-sm text-emerald-600 [@media(prefers-color-scheme:dark)]:text-emerald-400'
                  }
                >
                  {feedback.message}
                </p>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
