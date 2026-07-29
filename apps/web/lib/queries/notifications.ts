import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { apiFetch } from "@/lib/api"
import type { AppNotification } from "@/lib/types"

const UNREAD_KEY = ["notifications", "unread"] as const

export function useUnreadNotifications() {
  return useQuery({
    queryKey: UNREAD_KEY,
    queryFn: () => apiFetch<AppNotification[]>("/notifications/unread"),
    refetchInterval: 30_000,
  })
}

export function useMarkNotificationRead() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (notificationId: string) =>
      apiFetch<{ status: string }>(`/notifications/${notificationId}/read`, { method: "POST" }),
    onMutate: async (notificationId: string) => {
      await queryClient.cancelQueries({ queryKey: UNREAD_KEY })
      const previous = queryClient.getQueryData<AppNotification[]>(UNREAD_KEY)
      queryClient.setQueryData<AppNotification[]>(
        UNREAD_KEY,
        (old) => old?.filter((n) => n.id !== notificationId) ?? old
      )
      return { previous }
    },
    onError: (_err, _id, context) => {
      if (context?.previous) queryClient.setQueryData(UNREAD_KEY, context.previous)
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: UNREAD_KEY })
    },
  })
}
