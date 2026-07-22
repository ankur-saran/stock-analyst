import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth-options"

// Server Component counterpart to lib/api.ts's apiFetch — that one relies on
// next-auth/react's getSession(), which is client-only, so server components
// (coverage list/detail) need getServerSession(authOptions) instead.
export async function apiFetchServer<T = unknown>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const session = await getServerSession(authOptions)
  const accessToken = session?.accessToken

  const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}${path}`, {
    ...options,
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...options?.headers,
    },
  })

  if (!response.ok) {
    const text = await response.text()
    let message = text
    try {
      const body = JSON.parse(text)
      message = body?.detail ?? body?.title ?? text
    } catch {
      // body wasn't JSON (problem+json) — fall back to raw text
    }
    throw new Error(message || response.statusText)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return response.json() as Promise<T>
}
