'use client'

import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { Check, Loader2, Trash2, Upload } from 'lucide-react'
import { useAuth } from '@/components/auth/auth-guard'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { updateExpertProfile } from '@/lib/api'

type Profile = {
  name: string
  bio: string
  photo: string
}

const BIO_LIMIT = 280

function getInitials(name: string) {
  return (
    name
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase())
      .join('') || '?'
  )
}

function Avatar({ photo, name, className }: { photo: string; name: string; className: string }) {
  if (!photo) {
    return (
      <span
        aria-hidden="true"
        className={`flex items-center justify-center rounded-full bg-muted font-semibold text-muted-foreground ${className}`}
      >
        {getInitials(name)}
      </span>
    )
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element -- supports uploaded data URLs
    <img src={photo} alt={`Фото: ${name || 'эксперт'}`} className={`rounded-full object-cover ${className}`} />
  )
}

function resizeImageToDataUrl(file: File, maxSize = 256): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('Не удалось прочитать файл'))
    reader.onload = () => {
      const img = new Image()
      img.onerror = () => reject(new Error('Неподдерживаемый формат изображения'))
      img.onload = () => {
        const scale = Math.min(1, maxSize / Math.max(img.width, img.height))
        const width = Math.max(1, Math.round(img.width * scale))
        const height = Math.max(1, Math.round(img.height * scale))
        const canvas = document.createElement('canvas')
        canvas.width = width
        canvas.height = height
        const ctx = canvas.getContext('2d')
        if (!ctx) {
          reject(new Error('Canvas недоступен'))
          return
        }
        ctx.drawImage(img, 0, 0, width, height)
        resolve(canvas.toDataURL('image/jpeg', 0.85))
      }
      img.src = String(reader.result)
    }
    reader.readAsDataURL(file)
  })
}

export function ProfileEditor() {
  const { expert, token, updateExpertState } = useAuth()
  const initial: Profile = {
    name: expert?.name ?? '',
    bio: expert?.bio ?? '',
    photo: expert?.avatar_url ?? '',
  }

  const [draft, setDraft] = useState<Profile>(initial)
  const [saved, setSaved] = useState<Profile>(initial)
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved'>('idle')
  const [nameError, setNameError] = useState('')
  const [apiError, setApiError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!expert) return
    const next: Profile = {
      name: expert.name ?? '',
      bio: expert.bio ?? '',
      photo: expert.avatar_url ?? '',
    }
    setSaved(next)
    setDraft(next)
  }, [expert?.id, expert?.name, expert?.bio, expert?.avatar_url])

  const isDirty = draft.name !== saved.name || draft.bio !== saved.bio || draft.photo !== saved.photo

  const update = (patch: Partial<Profile>) => {
    setDraft((prev) => ({ ...prev, ...patch }))
    setSaveState('idle')
    setApiError(null)
  }

  const handlePhotoChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || !file.type.startsWith('image/')) return
    try {
      const dataUrl = await resizeImageToDataUrl(file, 256)
      update({ photo: dataUrl })
    } catch (err) {
      setApiError(err instanceof Error ? err.message : 'Не удалось обработать фото')
    }
  }

  const handleSave = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!token) return
    if (draft.name.trim().length < 2) {
      setNameError('Введите имя — минимум 2 символа')
      document.getElementById('expert-name')?.focus()
      return
    }
    setNameError('')
    setApiError(null)
    setSaveState('saving')
    try {
      const updated = await updateExpertProfile(
        {
          name: draft.name.trim(),
          bio: draft.bio.trim() || null,
          avatar_url: draft.photo.trim() || null,
        },
        token,
      )
      const next: Profile = {
        name: updated.name,
        bio: updated.bio ?? '',
        photo: updated.avatar_url ?? '',
      }
      setDraft(next)
      setSaved(next)
      updateExpertState(updated)
      setSaveState('saved')
    } catch (err) {
      setApiError(err instanceof Error ? err.message : 'Не удалось сохранить профиль')
      setSaveState('idle')
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)] lg:gap-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Профиль эксперта</CardTitle>
          <CardDescription>Эти данные видят участники на страницах ваших мероприятий</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSave} noValidate className="flex flex-col gap-5">
            <div className="flex items-center gap-4">
              <Avatar photo={draft.photo} name={draft.name} className="size-20 shrink-0 text-xl" />
              <div className="flex flex-col gap-1.5">
                <input
                  ref={fileInputRef}
                  id="expert-photo"
                  type="file"
                  accept="image/*"
                  className="sr-only"
                  onChange={handlePhotoChange}
                />
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    className="w-fit"
                    onClick={() => fileInputRef.current?.click()}
                  >
                    <Upload aria-hidden="true" />
                    Загрузить фото
                  </Button>
                  {draft.photo && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => update({ photo: '' })}
                      className="gap-1.5 text-muted-foreground hover:text-destructive"
                    >
                      <Trash2 aria-hidden="true" className="size-3.5" />
                      Удалить
                    </Button>
                  )}
                </div>
                <p className="text-xs text-muted-foreground">Необязательно. Без фото отображаются ваши инициалы.</p>
              </div>
            </div>

            <div className="flex flex-col gap-2">
              <Label htmlFor="expert-name">Имя</Label>
              <Input
                id="expert-name"
                value={draft.name}
                autoComplete="name"
                aria-invalid={nameError ? true : undefined}
                aria-describedby={nameError ? 'expert-name-error' : undefined}
                onChange={(event) => {
                  update({ name: event.target.value })
                  if (nameError && event.target.value.trim().length >= 2) setNameError('')
                }}
                className="h-10"
              />
              {nameError && (
                <p id="expert-name-error" className="text-sm text-destructive">
                  {nameError}
                </p>
              )}
            </div>

            <div className="flex flex-col gap-2">
              <div className="flex items-baseline justify-between gap-2">
                <Label htmlFor="expert-bio">О себе</Label>
                <span className="text-xs tabular-nums text-muted-foreground" aria-live="polite">
                  {draft.bio.length}/{BIO_LIMIT}
                </span>
              </div>
              <Textarea
                id="expert-bio"
                value={draft.bio}
                maxLength={BIO_LIMIT}
                rows={4}
                placeholder="Расскажите коротко о себе и своём опыте"
                onChange={(event) => update({ bio: event.target.value })}
                className="min-h-28 resize-y leading-relaxed"
              />
            </div>

            {apiError && (
              <p role="alert" className="text-sm text-destructive">
                {apiError}
              </p>
            )}

            <div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center">
              <Button
                type="submit"
                disabled={!isDirty || saveState === 'saving'}
                className="h-10 w-full bg-accent-cta px-5 text-accent-cta-foreground hover:bg-accent-cta/90 sm:w-fit"
              >
                {saveState === 'saving' && <Loader2 aria-hidden="true" className="animate-spin" />}
                {saveState === 'saving' ? 'Сохраняем…' : 'Сохранить'}
              </Button>
              <p role="status" className="text-sm text-muted-foreground">
                {saveState === 'saved' && !isDirty ? (
                  <span className="inline-flex items-center gap-1.5">
                    <Check aria-hidden="true" className="size-4 text-accent-cta" />
                    Изменения сохранены
                  </span>
                ) : isDirty ? (
                  'Есть несохранённые изменения'
                ) : null}
              </p>
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Превью профиля</CardTitle>
          <CardDescription>Так блок «Об эксперте» выглядит для участников</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="overflow-hidden rounded-xl border bg-background">
            <div className="h-16 bg-gradient-to-br from-accent-cta/80 to-accent-cta-soft/60" />
            <div className="-mt-9 flex flex-col items-center gap-2 px-4 pb-5 text-center">
              <Avatar
                photo={saved.photo}
                name={saved.name}
                className="size-[4.5rem] border-4 border-background text-lg"
              />
              <p className="text-balance font-semibold text-foreground">{saved.name || 'Эксперт'}</p>
              {expert?.email && (
                <p className="text-xs text-muted-foreground">{expert.email}</p>
              )}
              <p className="line-clamp-3 text-pretty text-xs leading-relaxed text-muted-foreground">
                {saved.bio || 'Описание пока не заполнено'}
              </p>
            </div>
          </div>
          <p className="text-xs text-muted-foreground">Превью обновится после сохранения профиля</p>
        </CardContent>
      </Card>
    </div>
  )
}
