const EXTRACTOR_URL = '/api/extractor'
const COMPOSER_URL = '/api/composer'
const VK_PUBLISHER_URL = '/api/vk-publisher'
const MAILER_URL = '/api/mailer'

export type ExtractResponse = {
  title: string
  date: string | null
  location: string | null
  price: number | null
}

export type ExpertUser = {
  id: string
  email: string
  name: string
  bio?: string | null
}

export type AuthResponse = {
  access_token: string
  token_type: string
  expert: ExpertUser
}

export type PublicationItem = {
  id: string
  channel: string
  status: string
  external_url: string | null
  sent_count: number
  published_at: string | null
}

export type EventItem = {
  id: string
  expert_id: string
  title: string
  description: string | null
  raw_text: string | null
  date: string | null
  location: string | null
  is_online: boolean
  price: number | null
  status: string
  subscribers_count: number
  publications: PublicationItem[]
  created_at: string | null
}

export type EventCreatePayload = {
  title: string
  date: string | null
  location: string | null
  price: number | null
  raw_text?: string | null
  description?: string | null
  is_online?: boolean
}

export type PublicEventApiResponse = {
  id: string
  title: string
  description: string | null
  raw_text: string | null
  date: string | null
  location: string | null
  is_online: boolean
  price: number | null
  status: string
  subscribers_count: number
  expert: {
    name: string
    bio: string | null
    avatar_url: string | null
  }
}

export type SubscribeResponse = {
  status: string
  id: string
  event_id: string
  name: string
  email: string
  message: string
}

export type PublishVkResponse = {
  status: string
  publication_id: string
  event_id: string
  channel: string
  external_url: string
  published_at: string
  post_text: string
  message: string
}

export type MailerSendResponse = {
  status: string
  publication_id: string
  event_id: string
  channel: string
  sent_count: number
  recipients: string[]
  published_at: string
  message: string
}

export type PageBlock = {
  type: string
  order: number
  data: Record<string, unknown>
}

export type ComposeResponse = {
  event_id: string
  blocks: PageBlock[]
}

export class ApiError extends Error {
  status: number | null

  constructor(message: string, status: number | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(
  url: string,
  options: { method?: 'GET' | 'POST'; body?: unknown; token?: string | null } = {},
): Promise<T> {
  const { method = 'GET', body, token } = options
  let response: Response
  try {
    response = await fetch(url, {
      method,
      headers: {
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    })
  } catch {
    throw new ApiError('Сервис недоступен. Проверьте соединение и попробуйте ещё раз.')
  }

  if (!response.ok) {
    let detail = `Ошибка сервера (${response.status})`
    try {
      const data = await response.json()
      if (typeof data?.detail === 'string') {
        detail = data.detail
      } else if (Array.isArray(data?.detail) && data.detail[0]?.msg) {
        detail = String(data.detail[0].msg)
      }
    } catch {
      // тело ответа не JSON — оставляем сообщение по умолчанию
    }
    throw new ApiError(detail, response.status)
  }

  return (await response.json()) as T
}

export function registerExpert(
  name: string,
  email: string,
  password: string,
): Promise<AuthResponse> {
  return request<AuthResponse>(`${EXTRACTOR_URL}/auth/register`, {
    method: 'POST',
    body: { name, email, password },
  })
}

export function loginExpert(email: string, password: string): Promise<AuthResponse> {
  return request<AuthResponse>(`${EXTRACTOR_URL}/auth/login`, {
    method: 'POST',
    body: { email, password },
  })
}

export function fetchCurrentExpert(token: string): Promise<ExpertUser> {
  return request<ExpertUser>(`${EXTRACTOR_URL}/auth/me`, {
    method: 'GET',
    token,
  })
}

export function extractAnnouncement(rawText: string, token: string): Promise<ExtractResponse> {
  return request<ExtractResponse>(`${EXTRACTOR_URL}/extract`, {
    method: 'POST',
    body: { raw_text: rawText },
    token,
  })
}

export function createEvent(payload: EventCreatePayload, token: string): Promise<EventItem> {
  return request<EventItem>(`${EXTRACTOR_URL}/events`, {
    method: 'POST',
    body: payload,
    token,
  })
}

export function listMyEvents(token: string): Promise<EventItem[]> {
  return request<EventItem[]>(`${EXTRACTOR_URL}/events`, {
    method: 'GET',
    token,
  })
}

export function getPublicEventById(eventId: string): Promise<PublicEventApiResponse> {
  return request<PublicEventApiResponse>(`${EXTRACTOR_URL}/events/${encodeURIComponent(eventId)}`, {
    method: 'GET',
  })
}

export function subscribeToEvent(
  eventId: string,
  name: string,
  email: string,
): Promise<SubscribeResponse> {
  return request<SubscribeResponse>(`${EXTRACTOR_URL}/subscribe`, {
    method: 'POST',
    body: { event_id: eventId, name, email },
  })
}

export function publishEventToVk(eventId: string): Promise<PublishVkResponse> {
  return request<PublishVkResponse>(`${VK_PUBLISHER_URL}/publish`, {
    method: 'POST',
    body: { event_id: eventId },
  })
}

export function sendEventMailing(eventId: string): Promise<MailerSendResponse> {
  return request<MailerSendResponse>(`${MAILER_URL}/send`, {
    method: 'POST',
    body: { event_id: eventId },
  })
}

export function composePage(eventId: string): Promise<ComposeResponse> {
  return request<ComposeResponse>(`${COMPOSER_URL}/compose`, {
    method: 'POST',
    body: { event_id: eventId },
  })
}

/** id мероприятия из ?event=... в адресе страницы; "demo" — если не указан. */
export function getCurrentEventId(): string {
  if (typeof window === 'undefined') return 'demo'
  return new URLSearchParams(window.location.search).get('event') || 'demo'
}
