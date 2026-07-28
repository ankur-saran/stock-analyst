"use client"

import { useEffect, useRef, useState } from "react"
import { useSession } from "next-auth/react"

import type { Citation, TaskStreamEvent } from "@/lib/types"

export type TaskStreamStatus = "idle" | "connecting" | "streaming" | "complete" | "partial" | "error"

export interface TaskStreamState {
  status: TaskStreamStatus
  streamedContent: string
  citations: Citation[]
  citationCoveragePct: number | null
  outputId: string | null
  errorDetail: string | null
}

const INITIAL_STATE: TaskStreamState = {
  status: "idle",
  streamedContent: "",
  citations: [],
  citationCoveragePct: null,
  outputId: null,
  errorDetail: null,
}

function toWsUrl(apiUrl: string): string {
  return apiUrl.replace(/^http/, "ws")
}

/**
 * Owns the WebSocket lifecycle for one task: connects to
 * /ws/tasks/{taskId}, accumulates streamed content/citations, and tracks
 * terminal status. Reconnects if the tab was hidden and comes back while
 * still streaming -- the server re-checks task status on every connection
 * (see apps/api/routers/tasks.py::task_websocket), so a plain reconnect is
 * safe even if the task finished while the tab was backgrounded.
 */
export function useTaskStream(taskId: string | null): TaskStreamState {
  const { data: session } = useSession()
  const accessToken = session?.accessToken
  const [state, setState] = useState<TaskStreamState>(INITIAL_STATE)
  const wsRef = useRef<WebSocket | null>(null)
  const statusRef = useRef<TaskStreamStatus>("idle")

  useEffect(() => {
    statusRef.current = state.status
  }, [state.status])

  useEffect(() => {
    if (!taskId || !accessToken) {
      setState(INITIAL_STATE)
      return
    }

    setState(INITIAL_STATE)

    function open() {
      const base = toWsUrl(process.env.NEXT_PUBLIC_API_URL!)
      const ws = new WebSocket(`${base}/ws/tasks/${taskId}?token=${accessToken}`)
      wsRef.current = ws

      setState((prev) => ({ ...prev, status: "connecting" }))

      ws.onopen = () => setState((prev) => ({ ...prev, status: "streaming" }))

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data) as TaskStreamEvent

        switch (data.type) {
          case "chunk":
            setState((prev) => ({
              ...prev,
              status: "streaming",
              streamedContent: prev.streamedContent + data.content,
              citations: [...prev.citations, ...data.citations],
            }))
            break
          case "complete":
            setState((prev) => ({
              ...prev,
              status: "complete",
              outputId: data.output_id,
              citationCoveragePct: data.citation_coverage_pct,
            }))
            break
          case "partial":
            setState((prev) => ({
              ...prev,
              status: "partial",
              outputId: data.output_id,
              citationCoveragePct: data.citation_coverage_pct,
            }))
            break
          case "already_complete":
            setState((prev) => ({ ...prev, status: "complete", outputId: data.output_id }))
            break
          case "error":
            setState((prev) => ({ ...prev, status: "error", errorDetail: data.detail }))
            break
          case "progress":
          case "citation_found":
          case "enforcer_running":
          case "enforcer_result":
            // No dedicated UI surface for these yet beyond the live chunk
            // stream and the terminal citation-coverage badge.
            break
        }
      }

      ws.onerror = () => {
        setState((prev) =>
          prev.status === "complete" || prev.status === "partial" ? prev : { ...prev, status: "error" }
        )
      }
    }

    open()

    function onVisibilityChange() {
      if (document.visibilityState !== "visible") return
      if (statusRef.current !== "streaming" && statusRef.current !== "connecting") return
      if (wsRef.current?.readyState === WebSocket.OPEN) return
      open()
    }
    document.addEventListener("visibilitychange", onVisibilityChange)

    return () => {
      document.removeEventListener("visibilitychange", onVisibilityChange)
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [taskId, accessToken])

  return state
}
