"use client"

import { CheckCircle2, Clock, Loader2, RotateCw, TriangleAlert, XCircle } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import type { IngestStatus } from "@/lib/types"

interface DocumentStatusBadgeProps {
  status: IngestStatus
  onRetry?: () => void
  retrying?: boolean
}

export function DocumentStatusBadge({ status, onRetry, retrying }: DocumentStatusBadgeProps) {
  switch (status) {
    case "pending":
      return (
        <Badge variant="outline" className="gap-1 border-slate-300 bg-slate-100 text-slate-600">
          <Clock className="h-3 w-3" />
          Queued
        </Badge>
      )

    case "indexing":
      return (
        <Badge variant="outline" className="gap-1 border-yellow-300 bg-yellow-100 text-yellow-800">
          <Loader2 className="h-3 w-3 animate-spin" />
          Indexing
        </Badge>
      )

    case "indexed":
      return (
        <Badge variant="outline" className="gap-1 border-green-300 bg-green-100 text-green-800">
          <CheckCircle2 className="h-3 w-3" />
          Indexed
        </Badge>
      )

    case "failed":
      return (
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="gap-1 border-red-300 bg-red-100 text-red-800">
            <XCircle className="h-3 w-3" />
            Failed
          </Badge>
          {onRetry && (
            <Button
              size="sm"
              variant="ghost"
              className="h-6 px-2 text-xs"
              onClick={onRetry}
              disabled={retrying}
            >
              <RotateCw className={cn("h-3 w-3 mr-1", retrying && "animate-spin")} />
              Retry
            </Button>
          )}
        </div>
      )

    case "review_needed":
      return (
        <Tooltip>
          <TooltipTrigger asChild>
            <Badge
              variant="outline"
              className="cursor-default gap-1 border-orange-300 bg-orange-100 text-orange-800"
            >
              <TriangleAlert className="h-3 w-3" />
              Review Needed
            </Badge>
          </TooltipTrigger>
          <TooltipContent>Text extraction &lt; 50%. Manual review recommended.</TooltipContent>
        </Tooltip>
      )
  }
}
