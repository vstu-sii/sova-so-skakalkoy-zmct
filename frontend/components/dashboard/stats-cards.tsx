import type { EventItem } from '@/lib/api'

export function StatsCards({ events }: { events: EventItem[] }) {
  const total = events.length
  const published = events.filter((e) => e.status === 'published').length
  const drafts = events.filter((e) => e.status !== 'published').length

  const stats = [
    { label: 'Всего мероприятий', value: total },
    { label: 'Опубликовано', value: published },
    { label: 'Черновики', value: drafts },
  ]

  return (
    <section aria-label="Статистика">
      <dl className="grid grid-cols-3 gap-3 sm:gap-4">
        {stats.map((stat) => (
          <div
            key={stat.label}
            className="flex flex-col gap-1 rounded-xl border bg-card p-3 text-card-foreground sm:p-5"
          >
            <dt className="text-xs leading-snug text-muted-foreground sm:text-sm">{stat.label}</dt>
            <dd className="text-2xl font-semibold tracking-tight tabular-nums sm:text-3xl">
              {stat.value}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  )
}
