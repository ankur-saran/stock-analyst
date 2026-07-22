import { getSession } from "next-auth/react"
import type { Session } from "next-auth"

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string
  ) {
    super(message)
    this.name = "ApiError"
  }
}

export async function apiFetch<T = unknown>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const session = (await getSession()) as (Session & { accessToken?: string }) | null
  const accessToken = session?.accessToken

  const response = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL}${path}`,
    {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        ...options?.headers,
      },
    }
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

  if (response.status === 204) {
    return undefined as T
  }

  return response.json() as Promise<T>
}
