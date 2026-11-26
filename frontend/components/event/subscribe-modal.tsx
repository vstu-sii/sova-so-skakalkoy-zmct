'use client'

import { useState, type FormEvent } from 'react'
import { CircleCheck, Loader2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { subscribeToEvent } from '@/lib/api'

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/

type SubscribeModalProps = {
  eventId: string
  eventTitle: string
  onClose: () => void
  onSuccess?: () => void
}

export function SubscribeModal({ eventId, eventTitle, onClose, onSuccess }: SubscribeModalProps) {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (isLoading) return
    setError(null)

    const trimmedName = name.trim()
    const trimmedEmail = email.trim()

    if (trimmedName.length < 2) {
      setError('Введите имя (минимум 2 символа)')
      return
    }
    if (!EMAIL_PATTERN.test(trimmedEmail)) {
      setError('Введите корректный email, например name@mail.ru')
      return
    }

    setIsLoading(true)
    try {
      const res = await subscribeToEvent(eventId, trimmedName, trimmedEmail)
      setSuccessMessage(res.message || 'Вы успешно записались на мероприятие!')
      onSuccess?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось записаться на мероприятие')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="subscribe-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs"
    >
      <Card className="w-full max-w-md shadow-xl">
        <CardHeader className="flex flex-row items-start justify-between gap-4">
          <div className="flex flex-col gap-1">
            <CardTitle id="subscribe-modal-title" className="text-xl">
              Запись на мероприятие
            </CardTitle>
            <CardDescription className="text-pretty">{eventTitle}</CardDescription>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Закрыть окно записи"
            onClick={onClose}
            disabled={isLoading}
          >
            <X aria-hidden="true" className="size-4" />
          </Button>
        </CardHeader>

        <CardContent>
          {successMessage ? (
            <div role="status" className="flex flex-col items-center gap-4 py-4 text-center">
              <span className="flex size-12 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-600">
                <CircleCheck aria-hidden="true" className="size-6" />
              </span>
              <div className="flex flex-col gap-1">
                <p className="text-lg font-semibold text-foreground">{successMessage}</p>
                <p className="text-sm text-muted-foreground">
                  Мы сохранили вашу заявку на <span className="font-medium text-foreground">{email.trim()}</span>.
                </p>
              </div>
              <Button type="button" onClick={onClose} className="w-full">
                Готово
              </Button>
            </div>
          ) : (
            <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="subscriber-name">Имя</Label>
                <Input
                  id="subscriber-name"
                  name="name"
                  autoComplete="name"
                  placeholder="Как к вам обращаться"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="h-10"
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="subscriber-email">Email</Label>
                <Input
                  id="subscriber-email"
                  name="email"
                  type="email"
                  inputMode="email"
                  autoComplete="email"
                  placeholder="name@mail.ru"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="h-10"
                />
              </div>

              {error && (
                <p role="alert" className="text-sm text-destructive">
                  {error}
                </p>
              )}

              <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
                <Button type="button" variant="outline" onClick={onClose} disabled={isLoading}>
                  Отмена
                </Button>
                <Button
                  type="submit"
                  disabled={isLoading}
                  className="gap-2 bg-accent-cta text-accent-cta-foreground hover:bg-accent-cta/90"
                >
                  {isLoading && <Loader2 aria-hidden="true" className="size-4 animate-spin" />}
                  {isLoading ? 'Отправляем…' : 'Записаться'}
                </Button>
              </div>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
