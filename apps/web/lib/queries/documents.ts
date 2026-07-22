import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { getSession } from "next-auth/react"
import type { Session } from "next-auth"

import { ApiError, apiFetch } from "@/lib/api"
import type { DocumentRow, TaskRead, TaskStatus, UploadTaskResponse } from "@/lib/types"

export function documentsKey(coverageId: string) {
  return ["coverages", coverageId, "documents"] as const
}

const IN_PROGRESS_STATUSES = new Set(["pending", "indexing"])

export function useDocuments(coverageId: string) {
  return useQuery({
    queryKey: documentsKey(coverageId),
    queryFn: () => apiFetch<DocumentRow[]>(`/coverages/${coverageId}/documents`),
    refetchInterval: (query) => {
      const data = query.state.data
      if (!data || data.length === 0) return false
      const hasInProgress = data.some((d) => IN_PROGRESS_STATUSES.has(d.ingest_status))
      return hasInProgress ? 3000 : false
    },
  })
}

// --- Upload (XHR, not fetch, so we get upload progress events) -------------

interface UploadVariables {
  file: File
  filingType: string
  period: string
  onProgress?: (percent: number) => void
}

async function uploadDocumentXhr(
  coverageId: string,
  { file, filingType, period, onProgress }: UploadVariables
): Promise<UploadTaskResponse> {
  const session = (await getSession()) as (Session & { accessToken?: string }) | null
  const accessToken = session?.accessToken

  const formData = new FormData()
  formData.append("file", file)
  formData.append("filing_type", filingType)
  formData.append("period", period)

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open("POST", `${process.env.NEXT_PUBLIC_API_URL}/coverages/${coverageId}/documents`)
    if (accessToken) {
      xhr.setRequestHeader("Authorization", `Bearer ${accessToken}`)
    }

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100))
      }
    }

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(xhr.responseText ? JSON.parse(xhr.responseText) : ({} as UploadTaskResponse))
        } catch {
          reject(new Error("Received an invalid response from the server"))
        }
      } else {
        let message = xhr.responseText
        try {
          const body = JSON.parse(xhr.responseText)
          message = body?.detail ?? body?.title ?? message
        } catch {
          // not JSON — use raw text
        }
        reject(new ApiError(xhr.status, message || xhr.statusText))
      }
    }

    xhr.onerror = () => reject(new Error("Network error during upload"))

    xhr.send(formData)
  })
}

export function useUploadDocument(coverageId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (variables: UploadVariables) => uploadDocumentXhr(coverageId, variables),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: documentsKey(coverageId) })
    },
  })
}

// --- Fetch from SEC EDGAR ----------------------------------------------------

interface FetchFromSecVariables {
  ticker: string
  formType: string
  year: number
}

export function useFetchFromSEC(coverageId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (variables: FetchFromSecVariables) =>
      apiFetch<UploadTaskResponse>(`/coverages/${coverageId}/documents`, {
        method: "POST",
        body: JSON.stringify({
          ticker: variables.ticker,
          form_type: variables.formType,
          year: variables.year,
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: documentsKey(coverageId) })
    },
  })
}

// --- Delete (optimistic) -----------------------------------------------------

export function useDeleteDocument(coverageId: string) {
  const queryClient = useQueryClient()
  const key = documentsKey(coverageId)

  return useMutation({
    mutationFn: (documentId: string) =>
      apiFetch<void>(`/coverages/${coverageId}/documents/${documentId}`, {
        method: "DELETE",
      }),
    onMutate: async (documentId: string) => {
      await queryClient.cancelQueries({ queryKey: key })
      const previous = queryClient.getQueryData<DocumentRow[]>(key)
      queryClient.setQueryData<DocumentRow[]>(
        key,
        (old) => old?.filter((d) => d.id !== documentId) ?? old
      )
      return { previous }
    },
    onError: (_err, _documentId, context) => {
      if (context?.previous) {
        queryClient.setQueryData(key, context.previous)
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: key })
    },
  })
}

// --- Retry (Failed -> re-enqueue ingestion) ----------------------------------

export function useRetryDocument(coverageId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (documentId: string) =>
      apiFetch<UploadTaskResponse>(`/coverages/${coverageId}/documents/${documentId}/retry`, {
        method: "POST",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: documentsKey(coverageId) })
    },
  })
}

// --- Task status polling ------------------------------------------------------

const TERMINAL_TASK_STATUSES = new Set<TaskStatus>(["completed", "failed", "cancelled"])

export function useTaskStatus(taskId: string | null | undefined) {
  return useQuery({
    queryKey: ["tasks", taskId] as const,
    queryFn: () => apiFetch<TaskRead>(`/tasks/${taskId}`),
    enabled: !!taskId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (!status || !TERMINAL_TASK_STATUSES.has(status)) return 2000
      return false
    },
  })
}
