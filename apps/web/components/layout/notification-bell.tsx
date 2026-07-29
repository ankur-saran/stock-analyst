"use client"

import { useRouter } from "next/navigation"
import { Bell } from "lucide-react"

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useMarkNotificationRead, useUnreadNotifications } from "@/lib/queries/notifications"
import { formatRelativeTime } from "@/lib/utils"
import type { AppNotification } from "@/lib/types"

const NOTIFICATION_LABEL: Record<AppNotification["type"], string> = {
  earnings_complete: "New quarterly analysis available",
}

export function NotificationBell() {
  const router = useRouter()
  const { data: notifications = [] } = useUnreadNotifications()
  const markRead = useMarkNotificationRead()

  function handleSelect(notification: AppNotification) {
    markRead.mutate(notification.id)
    router.push(`/coverages/${notification.coverage_id}/research/quarterly`)
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          className="relative rounded-lg p-2 text-slate-400 transition-colors hover:bg-slate-800 hover:text-white"
          aria-label="Notifications"
        >
          <Bell className="h-4 w-4" />
          {notifications.length > 0 && (
            <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-semibold leading-none text-white">
              {notifications.length > 9 ? "9+" : notifications.length}
            </span>
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-80">
        {notifications.length === 0 ? (
          <div className="px-3 py-6 text-center text-sm text-slate-500">No new notifications</div>
        ) : (
          notifications.map((notification) => (
            <DropdownMenuItem
              key={notification.id}
              onSelect={() => handleSelect(notification)}
              className="flex flex-col items-start gap-0.5 py-2"
            >
              <span className="text-sm font-medium text-slate-900">
                {NOTIFICATION_LABEL[notification.type] ?? notification.type} — {notification.ticker}
              </span>
              <span className="text-xs text-slate-500">
                {formatRelativeTime(notification.timestamp)}
              </span>
            </DropdownMenuItem>
          ))
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
