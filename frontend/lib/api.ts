/**
 * Gateway client.
 *
 * The Control Panel talks to the FastAPI gateway and to nothing else — never to
 * WAHA, Qdrant, Redis, PostgreSQL, or the ML Service
 * (08_Dashboard/01_Control_Panel_Overview.md §4). Every URL in this file starts
 * from NEXT_PUBLIC_API_URL for that reason: there is nowhere else to point it.
 *
 * Every Control Panel endpoint requires an operator session token
 * (`Authorization: Bearer …`). There is no unauthenticated read left: the old
 * NEXT_PUBLIC_DASHBOARD_KEY shared secret is gone, and a build-time constant in
 * a browser bundle was never a credential anyway.
 */

import { getToken, onUnauthorized } from "@/lib/session"

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

export type RiskLevel = "HIGH" | "MEDIUM" | "LOW" | "UNKNOWN"

export type Operator = {
  id: string
  email: string
  full_name: string
  last_login_at: string | null
}

export type LoginResult = {
  access_token: string
  token_type: string
  expires_at: string
  operator: Operator
}

export type DashboardSummary = {
  available: boolean
  reason?: string
  window_hours: number
  messages_processed?: number
  threats_detected?: number
  critical_threats?: number
  active_users?: number
  avg_response_latency_ms?: number | null
  severity_breakdown?: Record<string, number>
  intent_breakdown?: Record<string, number>
}

export type ActivityItem = {
  id: string
  at: string
  event: "MESSAGE_ANALYZED" | "THREAT_DETECTED"
  session: string
  chat_type: string
  input_type: string
  intent: string | null
  risk: RiskLevel
  similarity_score: number | null
  latency_ms: number | null
}

export type ActivityFeed = {
  available: boolean
  reason?: string
  transport?: string
  items: ActivityItem[]
}

export type RecentBlock<T> = { available: boolean; reason?: string; items: T[] }

export type ThreatItem = {
  id: string
  at: string
  session: string
  chat_type: string
  intent: string | null
  risk: RiskLevel
}

export type RecentPanels = {
  threats: RecentBlock<ThreatItem>
  incidents: RecentBlock<never>
  alerts: RecentBlock<never>
}

export type ServiceStatus = "HEALTHY" | "DOWN"

export type ServiceHealth = {
  status: "ok" | "degraded"
  degraded: string[]
  services: Record<string, { status: ServiceStatus; detail: Record<string, unknown> }>
}

export type WhatsAppSessions = {
  available: boolean
  active: number
  sessions: { name: string; status: string; engine: string | null }[]
}

/** Thrown when the gateway is unreachable or answers with an error status. */
export class GatewayError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message)
    this.name = "GatewayError"
  }
}

/** The session is gone (expired, revoked, or never existed). */
export class UnauthorizedError extends GatewayError {
  constructor(message = "sesi berakhir, silakan masuk lagi") {
    super(message, 401)
    this.name = "UnauthorizedError"
  }
}

async function request<T>(
  path: string,
  { method = "GET", body, signal, auth = true }: {
    method?: "GET" | "POST"
    body?: unknown
    signal?: AbortSignal
    auth?: boolean
  } = {},
): Promise<T> {
  const headers: Record<string, string> = {}
  if (body !== undefined) headers["Content-Type"] = "application/json"

  if (auth) {
    const token = getToken()
    if (!token) throw new UnauthorizedError("belum masuk")
    headers["Authorization"] = `Bearer ${token}`
  }

  let response: Response
  try {
    response = await fetch(`${API_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
      // Always live data: a cached security dashboard is a lying one.
      cache: "no-store",
    })
  } catch (error) {
    throw new GatewayError(error instanceof Error ? error.message : "gateway unreachable")
  }

  if (response.status === 401) {
    // One place decides what an expired session means, so every screen reacts
    // the same way instead of each rendering its own broken state.
    if (auth) onUnauthorized()
    throw new UnauthorizedError(await errorDetail(response, "email atau kata sandi salah"))
  }

  if (!response.ok) {
    throw new GatewayError(
      await errorDetail(response, `gateway returned ${response.status}`),
      response.status,
    )
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

/** FastAPI puts the human-readable reason in `detail`; fall back to the status. */
async function errorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    return typeof body.detail === "string" ? body.detail : fallback
  } catch {
    return fallback
  }
}

function get<T>(path: string, signal?: AbortSignal) {
  return request<T>(path, { signal })
}

export const api = {
  login: (email: string, password: string) =>
    request<LoginResult>("/api/v1/auth/login", {
      method: "POST",
      body: { email, password },
      auth: false,
    }),
  logout: () => request<void>("/api/v1/auth/logout", { method: "POST" }),
  me: (signal?: AbortSignal) => get<Operator>("/api/v1/auth/me", signal),

  summary: (signal?: AbortSignal) => get<DashboardSummary>("/api/v1/dashboard/summary", signal),
  activity: (limit = 15, signal?: AbortSignal) =>
    get<ActivityFeed>(`/api/v1/dashboard/activity?limit=${limit}`, signal),
  recent: (signal?: AbortSignal) => get<RecentPanels>("/api/v1/dashboard/recent", signal),
  services: (signal?: AbortSignal) => get<ServiceHealth>("/api/v1/system/services", signal),
  sessions: (signal?: AbortSignal) => get<WhatsAppSessions>("/api/v1/whatsapp/sessions", signal),
}
