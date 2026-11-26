'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { LogOut } from 'lucide-react'
import { useAuth } from '@/components/auth/auth-guard'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const navItems = [
  { href: '/', label: 'Мероприятия' },
  { href: '/new', label: 'Новый анонс' },
  { href: '/profile', label: 'Кабинет' },
]

export function ExpertNav() {
  const pathname = usePathname()
  const { expert, logout } = useAuth()

  return (
    <div className="flex items-center justify-between gap-3 sm:gap-4">
      <nav aria-label="Основная навигация" className="-mx-1 overflow-x-auto">
        <ul className="flex items-center gap-1 px-1">
          {navItems.map((item) => {
            const isActive = item.href === '/' ? pathname === '/' : pathname.startsWith(item.href)
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  aria-current={isActive ? 'page' : undefined}
                  className={cn(
                    'inline-flex h-8 items-center whitespace-nowrap rounded-md px-3 text-sm transition-colors',
                    isActive
                      ? 'bg-muted font-medium text-foreground'
                      : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  {item.label}
                </Link>
              </li>
            )
          })}
        </ul>
      </nav>

      <div className="flex items-center gap-2 border-l pl-3">
        {expert && (
          <span className="hidden max-w-40 truncate text-xs text-muted-foreground md:inline" title={expert.email}>
            {expert.name}
          </span>
        )}
        <Button type="button" variant="ghost" size="sm" onClick={logout} className="h-8 gap-1.5 px-2.5 text-xs">
          <LogOut aria-hidden="true" className="size-3.5" />
          Выйти
        </Button>
      </div>
    </div>
  )
}
