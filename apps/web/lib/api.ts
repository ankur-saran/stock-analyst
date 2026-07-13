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
    throw new ApiError(response.status, text)
  }

  return response.json() as Promise<T>
}
