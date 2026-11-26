'use client'

import Link from 'next/link'
import { Check, CircleCheck, ExternalLink, Loader2, Sparkles, X } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { ExtractedPreview } from '@/components/announcement/extracted-preview'
import { useAuth } from '@/components/auth/auth-guard'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { toExtractedAnnouncement } from '@/lib/adapters'
import { createEvent, extractAnnouncement, type EventItem, type ExtractResponse } from '@/lib/api'
import { EXAMPLE_RESULT, type ExtractedAnnouncement } from '@/lib/extract-announcement'

function toDateTimeLocalValue(iso: string | null): string {
  if (!iso) return ''
  // YYYY-MM-DD -> YYYY-MM-DDT12:00
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) {
    return `${iso}T12:00`
  }
  // YYYY-MM-DDTHH:MM:SS -> YYYY-MM-DDTHH:MM
  const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})/.exec(iso)
  return match ? match[1] : ''
}

export function AnnouncementForm() {
  const { token } = useAuth()
  const [text, setText] = useState('')
  const [extractedData, setExtractedData] = useState<ExtractedAnnouncement | null>(null)
  const [isExtracting, setIsExtracting] = useState(false)
  const [extractError, setExtractError] = useState<string | null>(null)

  // Human-in-the-loop modal state
  const [showConfirmModal, setShowConfirmModal] = useState(false)
  const [draftTitle, setDraftTitle] = useState('')
  const [draftDate, setDraftDate] = useState('')
  const [draftLocation, setDraftLocation] = useState('')
  const [draftPrice, setDraftPrice] = useState('')
  const [draftDescription, setDraftDescription] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const [createdEvent, setCreatedEvent] = useState<EventItem | null>(null)

  function openConfirmation(parsed: ExtractResponse, rawText: string) {
    setDraftTitle(parsed.title || '')
    setDraftDate(toDateTimeLocalValue(parsed.date))
    setDraftLocation(parsed.location || '')
    setDraftPrice(parsed.price !== null && parsed.price !== undefined ? String(parsed.price) : '')
    setDraftDescription(rawText.trim())
    setSaveError(null)
    setShowConfirmModal(true)
  }

  async function handleExtract(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!text.trim() || !token || isExtracting) return
    setIsExtracting(true)
    setExtractError(null)
    setCreatedEvent(null)
    try {
      const parsed = await extractAnnouncement(text, token)
      setExtractedData(toExtractedAnnouncement(parsed))
      openConfirmation(parsed, text)
    } catch (err) {
      setExtractError(err instanceof Error ? err.message : 'Не удалось извлечь данные')
    } finally {
      setIsExtracting(false)
    }
  }

  async function handleConfirmSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!token || isSaving) return

    const trimmedTitle = draftTitle.trim()
    if (!trimmedTitle) {
      setSaveError('Укажите название мероприятия')
      return
    }

    let parsedPrice: number | null = null
    if (draftPrice.trim() !== '') {
      const num = Number(draftPrice.replace(',', '.'))
      if (Number.isNaN(num) || num < 0) {
        setSaveError('Цена должна быть неотрицательным числом')
        return
      }
      parsedPrice = num
    }

    setIsSaving(true)
    setSaveError(null)
    try {
      const saved = await createEvent(
        {
          title: trimmedTitle,
          date: draftDate.trim() ? draftDate.trim() : null,
          location: draftLocation.trim() ? draftLocation.trim() : null,
          price: parsedPrice,
          raw_text: text.trim(),
          description: draftDescription.trim() || text.trim(),
        },
        token,
      )
      setCreatedEvent(saved)
      setShowConfirmModal(false)
      setText('')
      setExtractedData(null)
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Не удалось сохранить мероприятие')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-10">
      {createdEvent && (
        <Card className="border-emerald-500/40 bg-emerald-500/5">
          <CardContent className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-600">
                <CircleCheck aria-hidden="true" className="size-5" />
              </span>
              <div className="flex flex-col gap-1">
                <p className="font-semibold text-foreground">Мероприятие сохранено: «{createdEvent.title}»</p>
                <p className="text-sm text-muted-foreground">
                  Теперь вы можете опубликовать его в ВК из дашборда или поделиться публичной ссылкой с участниками.
                </p>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="outline" size="sm" render={<Link href={`/event/${createdEvent.id}`} />} nativeButton={false}>
                <ExternalLink aria-hidden="true" className="size-3.5" />
                Публичная страница
              </Button>
              <Button size="sm" render={<Link href="/" />} nativeButton={false}>
                К списку мероприятий
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <form onSubmit={handleExtract} className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <Label htmlFor="announcement">Текст анонса</Label>
          <Textarea
            id="announcement"
            maxLength={1500}
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="В субботу в 19:00 встречаемся в кафе на Невском. Стоимость 2500₽, для своих 2000₽"
            aria-describedby="announcement-hint"
            className="min-h-56 resize-y p-4 text-base leading-relaxed md:text-base"
          />
          <p id="announcement-hint" className="text-sm text-muted-foreground">
            До 1500 символов. Система извлечёт название, дату, место и цену, а затем предложит проверить и отредактировать данные перед сохранением.
          </p>
        </div>

        {extractError && (
          <p role="alert" className="text-sm text-destructive">
            {extractError}
          </p>
        )}

        <Button type="submit" size="lg" disabled={!text.trim() || !token || isExtracting} className="self-start gap-2">
          {isExtracting ? <Loader2 aria-hidden="true" className="size-4 animate-spin" /> : <Sparkles aria-hidden="true" />}
          {isExtracting ? 'Извлекаем…' : 'Извлечь данные'}
        </Button>
      </form>

      <ExtractedPreview data={extractedData ?? EXAMPLE_RESULT} isExample={extractedData === null} />

      {showConfirmModal && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="confirm-modal-title"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs"
        >
          <Card className="max-h-[90dvh] w-full max-w-lg overflow-y-auto shadow-xl">
            <CardHeader className="flex flex-row items-start justify-between gap-4">
              <div className="flex flex-col gap-1">
                <CardTitle id="confirm-modal-title" className="text-xl">
                  Подтверждение данных
                </CardTitle>
                <CardDescription>
                  Проверьте и при необходимости исправьте данные перед сохранением в базу
                </CardDescription>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label="Закрыть окно подтверждения"
                onClick={() => setShowConfirmModal(false)}
                disabled={isSaving}
              >
                <X aria-hidden="true" className="size-4" />
              </Button>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleConfirmSave} className="flex flex-col gap-4">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="confirm-title">Название мероприятия</Label>
                  <Input
                    id="confirm-title"
                    value={draftTitle}
                    onChange={(e) => setDraftTitle(e.target.value)}
                    placeholder="Например: Медитация для начинающих"
                    required
                  />
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="confirm-date">Дата и время</Label>
                    <Input
                      id="confirm-date"
                      type="datetime-local"
                      value={draftDate}
                      onChange={(e) => setDraftDate(e.target.value)}
                    />
                  </div>

                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="confirm-price">Цена (₽)</Label>
                    <Input
                      id="confirm-price"
                      type="number"
                      min="0"
                      step="1"
                      placeholder="0 — бесплатно"
                      value={draftPrice}
                      onChange={(e) => setDraftPrice(e.target.value)}
                    />
                  </div>
                </div>

                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="confirm-location">Место проведения</Label>
                  <Input
                    id="confirm-location"
                    value={draftLocation}
                    onChange={(e) => setDraftLocation(e.target.value)}
                    placeholder="Кафе на Невском или Онлайн"
                  />
                </div>

                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="confirm-description">Описание</Label>
                  <Textarea
                    id="confirm-description"
                    rows={4}
                    value={draftDescription}
                    onChange={(e) => setDraftDescription(e.target.value)}
                    className="resize-y"
                  />
                </div>

                {saveError && (
                  <p role="alert" className="text-sm text-destructive">
                    {saveError}
                  </p>
                )}

                <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setShowConfirmModal(false)}
                    disabled={isSaving}
                  >
                    Отмена
                  </Button>
                  <Button type="submit" disabled={isSaving} className="gap-2">
                    {isSaving ? (
                      <Loader2 aria-hidden="true" className="size-4 animate-spin" />
                    ) : (
                      <Check aria-hidden="true" className="size-4" />
                    )}
                    {isSaving ? 'Сохраняем…' : 'Подтвердить'}
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
