"use client"

import { useState } from "react"
import { getSession } from "next-auth/react"
import type { Session } from "next-auth"
import { Download, Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { ApiError } from "@/lib/api"

interface DownloadReportButtonProps {
  coverageId: string
  ticker: string
}

// Not built on lib/api.ts's apiFetch — that helper always parses the
// response as JSON, but this endpoint returns a raw PDF octet stream that
// needs to become a Blob and trigger a browser download instead.
export function DownloadReportButton({ coverageId, ticker }: DownloadReportButtonProps) {
  const [isDownloading, setIsDownloading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleDownload() {
    setIsDownloading(true)
    setError(null)
    try {
      const session = (await getSession()) as (Session & { accessToken?: string }) | null
      const accessToken = session?.accessToken

      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/coverages/${coverageId}/report.pdf`,
        { headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {} }
      )

      if (!response.ok) {
        const text = await response.text()
        let message = text
        try {
          const body = JSON.parse(text)
          message = body?.detail ?? body?.title ?? text
        } catch {
          // body wasn't JSON (problem+json) — fall back to raw text
        }
        throw new ApiError(response.status, message || response.statusText)
      }

      const blob = await response.blob()
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = `${ticker}_report.pdf`
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to generate report")
    } finally {
      setIsDownloading(false)
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <Button variant="outline" size="sm" onClick={handleDownload} disabled={isDownloading}>
        {isDownloading ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Generating…
          </>
        ) : (
          <>
            <Download className="mr-2 h-4 w-4" />
            Download Report
          </>
        )}
      </Button>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  )
}
