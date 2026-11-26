import type { ComposeResponse, ExtractResponse, PublicEventApiResponse } from '@/lib/api'
import type { ExtractedAnnouncement } from '@/lib/extract-announcement'
import { publicEvent, type PublicEvent } from '@/lib/public-event'

const MONTHS_GENITIVE = [
  'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
]
const WEEKDAYS = [
  'воскресенье', 'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота',
]

const ISO_RE = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/

type ParsedDate = {
  date: string // "19 октября"
  weekday: string // "суббота"
  time: string | null // "19:00"
}

export function parseIsoDate(iso: string | null): ParsedDate | null {
  if (!iso) return null
  const m = ISO_RE.exec(iso)
  if (!m) return null
  const [, y, mo, d, hh, mm] = m
  const weekday = WEEKDAYS[new Date(Date.UTC(Number(y), Number(mo) - 1, Number(d))).getUTCDay()]
  return {
    date: `${Number(d)} ${MONTHS_GENITIVE[Number(mo) - 1]}`,
    weekday,
    time: hh !== undefined ? `${hh}:${mm}` : null,
  }
}

export function formatEventDateTime(iso: string | null): string {
  const parsed = parseIsoDate(iso)
  if (!parsed) return 'Дата не указана'
  return parsed.time ? `${parsed.date}, ${parsed.time}` : parsed.date
}

function capitalize(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1)
}

export function formatRubPrice(amount: number | null): string {
  if (amount === null || amount === undefined) return 'Не указана'
  if (amount === 0) return 'Бесплатно'
  return `${new Intl.NumberFormat('ru-RU').format(amount)}₽`
}

/** Ответ extractor → формат, который ждёт ExtractedPreview. */
export function toExtractedAnnouncement(response: ExtractResponse): ExtractedAnnouncement {
  const parsed = parseIsoDate(response.date)

  return {
    date: {
      day: parsed ? `${capitalize(parsed.weekday)}, ${parsed.date}` : null,
      time: parsed?.time ?? null,
    },
    place: response.location,
    prices:
      response.price === null
        ? []
        : [
            response.price === 0
              ? { amount: 0, label: 'Вход' }
              : { amount: response.price, label: 'Стандартный' },
          ],
  }
}

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null
}

/** Ответ GET /events/{id} → PublicEvent для публичной страницы /event/[id]. */
export function publicEventFromApi(api: PublicEventApiResponse): PublicEvent {
  const parsed = parseIsoDate(api.date)
  const rawDesc = (api.description || api.raw_text || '').trim()
  const paragraphs = rawDesc
    ? rawDesc.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean)
    : ['Подробности мероприятия будут уточнены дополнительно.']

  return {
    title: api.title,
    tagline: paragraphs[0]?.slice(0, 160) || 'Приглашаем на встречу',
    date: parsed ? parsed.date : 'Дата уточняется',
    weekday: parsed ? parsed.weekday : '',
    time: parsed?.time ?? 'время уточняется',
    duration: 'по программе',
    venue: api.location || (api.is_online ? 'Онлайн' : 'Место уточняется'),
    address: api.location || (api.is_online ? 'Ссылка придёт после записи' : 'Адрес уточняется'),
    isOnline: api.is_online,
    price: formatRubPrice(api.price),
    friendsPrice: '',
    seatsLeft: Math.max(1, 20 - api.subscribers_count),
    subscribersCount: api.subscribers_count,
    description: paragraphs,
    expert: {
      name: api.expert.name || 'Эксперт',
      role: 'Организатор мероприятия',
      bio: api.expert.bio || 'Эксперт платформы.',
      photo: api.expert.avatar_url || '/images/expert.png',
    },
  }
}

/**
 * Ответ page-composer (блоки) → PublicEvent для страницы мероприятия.
 */
export function toPublicEvent(
  response: ComposeResponse,
  base: PublicEvent = publicEvent,
): PublicEvent {
  const event: PublicEvent = { ...base }
  const blocks = [...response.blocks].sort((a, b) => a.order - b.order)

  for (const block of blocks) {
    switch (block.type) {
      case 'hero': {
        event.title = asString(block.data.title) ?? event.title
        const parsed = parseIsoDate(asString(block.data.date))
        if (parsed) {
          event.date = parsed.date
          event.weekday = parsed.weekday
          if (parsed.time) event.time = parsed.time
        }
        break
      }
      case 'pricing': {
        const price = block.data.price
        if (typeof price === 'number') event.price = formatRubPrice(price)
        const friends = block.data.friends_price
        if (typeof friends === 'number') event.friendsPrice = formatRubPrice(friends)
        break
      }
      case 'location': {
        const location = asString(block.data.location)
        if (location) {
          event.venue = location
          event.address = location
        }
        break
      }
      case 'description': {
        const description = asString(block.data.description)
        if (description) event.description = description.split(/\n{2,}/)
        break
      }
    }
  }

  return event
}
