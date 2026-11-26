'use client'

import { useState, type FormEvent } from 'react'
import { Check, Loader2, Mail, Settings2, Unplug, X } from 'lucide-react'
import { useAuth } from '@/components/auth/auth-guard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  connectEmailChannel,
  connectVkChannel,
  disconnectEmailChannel,
  disconnectVkChannel,
} from '@/lib/api'

type ActiveModal = 'vk' | 'email' | null

const SMTP_PRESETS = [
  { label: 'Mail.ru', host: 'smtp.mail.ru' },
  { label: 'Яндекс', host: 'smtp.yandex.ru' },
  { label: 'Gmail', host: 'smtp.gmail.com' },
] as const

export function Channels() {
  const { expert, token, updateExpertState } = useAuth()
  const [activeModal, setActiveModal] = useState<ActiveModal>(null)
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  // VK form state
  const [vkGroupId, setVkGroupId] = useState('')
  const [vkToken, setVkToken] = useState('')
  const [vkError, setVkError] = useState<string | null>(null)

  // Email SMTP form state
  const [smtpHost, setSmtpHost] = useState('smtp.mail.ru')
  const [smtpUser, setSmtpUser] = useState('')
  const [smtpPassword, setSmtpPassword] = useState('')
  const [emailError, setEmailError] = useState<string | null>(null)

  const vkConnected = Boolean(expert?.vk_connected)
  const emailConnected = Boolean(expert?.email_connected)

  function openVkModal() {
    setVkGroupId(expert?.vk_group_id ?? '')
    setVkToken('')
    setVkError(null)
    setActiveModal('vk')
  }

  function openEmailModal() {
    setSmtpHost(expert?.smtp_host || 'smtp.mail.ru')
    setSmtpUser(expert?.smtp_user || expert?.email || '')
    setSmtpPassword('')
    setEmailError(null)
    setActiveModal('email')
  }

  async function handleSaveVk(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!token || busyAction) return
    setVkError(null)
    if (!vkGroupId.trim()) {
      setVkError('Укажите ID сообщества ВКонтакте')
      return
    }
    if (vkToken.trim().length < 10) {
      setVkError('Вставьте токен доступа ВКонтакте')
      return
    }
    setBusyAction('vk-save')
    try {
      const updated = await connectVkChannel(vkGroupId.trim(), vkToken.trim(), token)
      updateExpertState(updated)
      setActiveModal(null)
      setFeedback({ type: 'success', text: `Сообщество ВК (ID ${updated.vk_group_id}) подключено` })
    } catch (err) {
      setVkError(err instanceof Error ? err.message : 'Не удалось подключить ВКонтакте')
    } finally {
      setBusyAction(null)
    }
  }

  async function handleDisconnectVk() {
    if (!token || busyAction) return
    setBusyAction('vk-disconnect')
    setFeedback(null)
    try {
      const updated = await disconnectVkChannel(token)
      updateExpertState(updated)
      setFeedback({ type: 'success', text: 'Сообщество ВК отключено' })
    } catch (err) {
      setFeedback({
        type: 'error',
        text: err instanceof Error ? err.message : 'Не удалось отключить ВК',
      })
    } finally {
      setBusyAction(null)
    }
  }

  async function handleSaveEmail(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!token || busyAction) return
    setEmailError(null)
    if (!smtpHost.trim() || !smtpUser.trim() || !smtpPassword.trim()) {
      setEmailError('Заполните SMTP-сервер, email и пароль приложения')
      return
    }
    setBusyAction('email-save')
    try {
      const updated = await connectEmailChannel(
        smtpHost.trim(),
        smtpUser.trim(),
        smtpPassword.trim(),
        token,
      )
      updateExpertState(updated)
      setActiveModal(null)
      setFeedback({ type: 'success', text: `Почта ${updated.smtp_user} подключена для рассылок` })
    } catch (err) {
      setEmailError(err instanceof Error ? err.message : 'Не удалось подключить почту')
    } finally {
      setBusyAction(null)
    }
  }

  async function handleDisconnectEmail() {
    if (!token || busyAction) return
    setBusyAction('email-disconnect')
    setFeedback(null)
    try {
      const updated = await disconnectEmailChannel(token)
      updateExpertState(updated)
      setFeedback({ type: 'success', text: 'Почта для рассылок отключена' })
    } catch (err) {
      setFeedback({
        type: 'error',
        text: err instanceof Error ? err.message : 'Не удалось отключить почту',
      })
    } finally {
      setBusyAction(null)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {feedback && (
        <p
          role={feedback.type === 'error' ? 'alert' : 'status'}
          className={
            feedback.type === 'error'
              ? 'text-sm text-destructive'
              : 'text-sm text-emerald-600 [@media(prefers-color-scheme:dark)]:text-emerald-400'
          }
        >
          {feedback.text}
        </p>
      )}

      <div className="grid gap-3 sm:grid-cols-2 sm:gap-4">
        {/* ВКонтакте */}
        <Card className="py-4">
          <CardContent className="flex flex-col gap-4 px-4">
            <div className="flex items-start gap-3">
              <span
                aria-hidden="true"
                className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-[#0077FF] text-sm font-bold text-white"
              >
                VK
              </span>
              <div className="flex min-w-0 flex-1 flex-col gap-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="font-semibold text-foreground">ВКонтакте</h3>
                  {vkConnected ? (
                    <Badge className="border-transparent bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 [@media(prefers-color-scheme:dark)]:text-emerald-400">
                      <span aria-hidden="true" className="size-1.5 rounded-full bg-current" />
                      Подключено
                    </Badge>
                  ) : (
                    <Badge variant="secondary" className="text-muted-foreground">
                      Не подключено
                    </Badge>
                  )}
                </div>
                <p className="truncate text-sm text-muted-foreground">
                  {vkConnected
                    ? `Сообщество ID: ${expert?.vk_group_id}`
                    : 'Публикация анонсов в вашем сообществе ВК'}
                </p>
              </div>
            </div>

            <div className="flex gap-2">
              <Button
                type="button"
                variant={vkConnected ? 'outline' : 'default'}
                disabled={busyAction !== null}
                onClick={openVkModal}
                className="h-9 flex-1 gap-1.5"
              >
                <Settings2 aria-hidden="true" className="size-4" />
                {vkConnected ? 'Изменить' : 'Подключить'}
              </Button>
              {vkConnected && (
                <Button
                  type="button"
                  variant="ghost"
                  disabled={busyAction !== null}
                  onClick={handleDisconnectVk}
                  className="h-9 gap-1.5 text-muted-foreground hover:text-destructive"
                  aria-label="Отключить ВКонтакте"
                >
                  {busyAction === 'vk-disconnect' ? (
                    <Loader2 aria-hidden="true" className="size-4 animate-spin" />
                  ) : (
                    <Unplug aria-hidden="true" className="size-4" />
                  )}
                  Отключить
                </Button>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Email (SMTP) */}
        <Card className="py-4">
          <CardContent className="flex flex-col gap-4 px-4">
            <div className="flex items-start gap-3">
              <span
                aria-hidden="true"
                className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted text-foreground"
              >
                <Mail className="size-5" />
              </span>
              <div className="flex min-w-0 flex-1 flex-col gap-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="font-semibold text-foreground">Email (SMTP)</h3>
                  {emailConnected ? (
                    <Badge className="border-transparent bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 [@media(prefers-color-scheme:dark)]:text-emerald-400">
                      <span aria-hidden="true" className="size-1.5 rounded-full bg-current" />
                      Подключено
                    </Badge>
                  ) : (
                    <Badge variant="secondary" className="text-muted-foreground">
                      Не подключено
                    </Badge>
                  )}
                </div>
                <p className="truncate text-sm text-muted-foreground">
                  {emailConnected
                    ? `${expert?.smtp_user} (${expert?.smtp_host})`
                    : 'Рассылка писем участникам с вашей почты'}
                </p>
              </div>
            </div>

            <div className="flex gap-2">
              <Button
                type="button"
                variant={emailConnected ? 'outline' : 'default'}
                disabled={busyAction !== null}
                onClick={openEmailModal}
                className="h-9 flex-1 gap-1.5"
              >
                <Settings2 aria-hidden="true" className="size-4" />
                {emailConnected ? 'Изменить' : 'Подключить'}
              </Button>
              {emailConnected && (
                <Button
                  type="button"
                  variant="ghost"
                  disabled={busyAction !== null}
                  onClick={handleDisconnectEmail}
                  className="h-9 gap-1.5 text-muted-foreground hover:text-destructive"
                  aria-label="Отключить Email"
                >
                  {busyAction === 'email-disconnect' ? (
                    <Loader2 aria-hidden="true" className="size-4 animate-spin" />
                  ) : (
                    <Unplug aria-hidden="true" className="size-4" />
                  )}
                  Отключить
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Модалка подключения ВК */}
      {activeModal === 'vk' && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="vk-modal-title"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs"
        >
          <Card className="w-full max-w-md shadow-xl">
            <CardHeader className="flex flex-row items-start justify-between gap-4">
              <div className="flex flex-col gap-1">
                <CardTitle id="vk-modal-title" className="text-xl">
                  Подключение сообщества ВК
                </CardTitle>
                <CardDescription>
                  Посты будут публиковаться на стену указанного сообщества через VK API
                </CardDescription>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label="Закрыть"
                onClick={() => setActiveModal(null)}
                disabled={busyAction !== null}
              >
                <X aria-hidden="true" className="size-4" />
              </Button>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleSaveVk} className="flex flex-col gap-4">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="vk-group-id">ID сообщества ВК</Label>
                  <Input
                    id="vk-group-id"
                    placeholder="Например: 123456789 или club123456789"
                    value={vkGroupId}
                    onChange={(e) => setVkGroupId(e.target.value)}
                    className="h-10"
                  />
                  <p className="text-xs text-muted-foreground">
                    Числовой ID сообщества из настроек или ссылки вида vk.com/club123456789
                  </p>
                </div>

                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="vk-access-token">Токен доступа (access_token)</Label>
                  <Input
                    id="vk-access-token"
                    type="password"
                    autoComplete="off"
                    placeholder="vk1.a...."
                    value={vkToken}
                    onChange={(e) => setVkToken(e.target.value)}
                    className="h-10"
                  />
                  <p className="text-xs text-muted-foreground">
                    Для публикации на стене нужен пользовательский токен администратора с правами{' '}
                    <code>wall</code> и <code>groups</code>.
                  </p>
                </div>

                {vkError && (
                  <p role="alert" className="text-sm text-destructive">
                    {vkError}
                  </p>
                )}

                <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setActiveModal(null)}
                    disabled={busyAction !== null}
                  >
                    Отмена
                  </Button>
                  <Button type="submit" disabled={busyAction !== null} className="gap-1.5">
                    {busyAction === 'vk-save' ? (
                      <Loader2 aria-hidden="true" className="size-4 animate-spin" />
                    ) : (
                      <Check aria-hidden="true" className="size-4" />
                    )}
                    Сохранить
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Модалка подключения Email (SMTP) */}
      {activeModal === 'email' && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="email-modal-title"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs"
        >
          <Card className="w-full max-w-md shadow-xl">
            <CardHeader className="flex flex-row items-start justify-between gap-4">
              <div className="flex flex-col gap-1">
                <CardTitle id="email-modal-title" className="text-xl">
                  Подключение почты (SMTP)
                </CardTitle>
                <CardDescription>
                  Рассылки по вашим мероприятиям будут отправляться с этого ящика
                </CardDescription>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label="Закрыть"
                onClick={() => setActiveModal(null)}
                disabled={busyAction !== null}
              >
                <X aria-hidden="true" className="size-4" />
              </Button>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleSaveEmail} className="flex flex-col gap-4">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="smtp-host">SMTP-сервер</Label>
                  <div className="flex flex-wrap gap-1.5">
                    {SMTP_PRESETS.map((preset) => (
                      <Button
                        key={preset.host}
                        type="button"
                        variant={smtpHost === preset.host ? 'default' : 'outline'}
                        size="xs"
                        onClick={() => setSmtpHost(preset.host)}
                      >
                        {preset.label}
                      </Button>
                    ))}
                  </div>
                  <Input
                    id="smtp-host"
                    placeholder="smtp.mail.ru или smtp.mail.ru:587"
                    value={smtpHost}
                    onChange={(e) => setSmtpHost(e.target.value)}
                    className="h-10"
                  />
                  <p className="text-xs text-muted-foreground">
                    По умолчанию используется SSL-порт 465; для STARTTLS укажите порт через двоеточие (например,{' '}
                    <code>smtp.mail.ru:587</code>).
                  </p>
                </div>

                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="smtp-user">Email отправителя</Label>
                  <Input
                    id="smtp-user"
                    type="email"
                    autoComplete="email"
                    placeholder="expert@mail.ru"
                    value={smtpUser}
                    onChange={(e) => setSmtpUser(e.target.value)}
                    className="h-10"
                  />
                </div>

                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="smtp-password">Пароль для внешних приложений</Label>
                  <Input
                    id="smtp-password"
                    type="password"
                    autoComplete="new-password"
                    placeholder="Вставьте пароль приложения"
                    value={smtpPassword}
                    onChange={(e) => setSmtpPassword(e.target.value)}
                    className="h-10"
                  />
                </div>

                {emailError && (
                  <p role="alert" className="text-sm text-destructive">
                    {emailError}
                  </p>
                )}

                <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setActiveModal(null)}
                    disabled={busyAction !== null}
                  >
                    Отмена
                  </Button>
                  <Button type="submit" disabled={busyAction !== null} className="gap-1.5">
                    {busyAction === 'email-save' ? (
                      <Loader2 aria-hidden="true" className="size-4 animate-spin" />
                    ) : (
                      <Check aria-hidden="true" className="size-4" />
                    )}
                    Сохранить
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
