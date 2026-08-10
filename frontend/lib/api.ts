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
  threat_category: string
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
  threat_category: string
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

export type MessageLogItem = {
  id: string
  at: string
  session: string
  chat_type: string
  input_type: string
  extracted_text: string | null
  intent: string | null
  threat_category: string
  risk: RiskLevel
  similarity_score: number | null
  latency_ms: number | null
}

export type MessageLogs = {
  available: boolean
  reason?: string
  total: number
  items: MessageLogItem[]
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
    method?: "GET" | "POST" | "DELETE"
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

/**
 * Live Activity push over SSE, read by hand rather than `EventSource`.
 *
 * `EventSource` cannot send an `Authorization` header, and this gateway has no
 * cookie session to fall back on — every other call in this file proves that.
 * Putting the bearer token in the URL instead would leak it into server and
 * proxy access logs, which is worse than the manual `ReadableStream` parsing
 * below. See `app/api/v1/endpoints/dashboard.py::dashboard_activity_stream`.
 *
 * Resolves when the stream ends (server closed it, or `signal` aborted);
 * rejects on a connection or auth failure. The caller decides whether to
 * reconnect — this function makes exactly one attempt.
 */
async function streamActivity(onEvent: (item: ActivityItem) => void, signal: AbortSignal): Promise<void> {
  const token = getToken()
  if (!token) throw new UnauthorizedError("belum masuk")

  let response: Response
  try {
    response = await fetch(`${API_URL}/api/v1/dashboard/activity/stream`, {
      headers: { Authorization: `Bearer ${token}` },
      signal,
      cache: "no-store",
    })
  } catch (error) {
    throw new GatewayError(error instanceof Error ? error.message : "gateway unreachable")
  }

  if (response.status === 401) {
    onUnauthorized()
    throw new UnauthorizedError()
  }
  if (!response.ok || !response.body) {
    throw new GatewayError(await errorDetail(response, `gateway returned ${response.status}`), response.status)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""

  for (;;) {
    const { done, value } = await reader.read()
    if (done) return
    buffer += decoder.decode(value, { stream: true })

    let boundary = buffer.indexOf("\n\n")
    while (boundary !== -1) {
      const rawEvent = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      boundary = buffer.indexOf("\n\n")

      const data = rawEvent
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trim())
        .join("\n")
      if (!data) continue // keep-alive comment line (`: keep-alive`)

      try {
        onEvent(JSON.parse(data) as ActivityItem)
      } catch {
        // One malformed event must not kill a connection carrying many good
        // ones — drop it and keep reading.
      }
    }
  }
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
  changePassword: (currentPassword: string, newPassword: string) =>
    request<void>("/api/v1/auth/change-password", {
      method: "POST",
      body: { current_password: currentPassword, new_password: newPassword },
    }),

  summary: (signal?: AbortSignal) => get<DashboardSummary>("/api/v1/dashboard/summary", signal),
  activity: (limit = 15, signal?: AbortSignal) =>
    get<ActivityFeed>(`/api/v1/dashboard/activity?limit=${limit}`, signal),
  recent: (signal?: AbortSignal) => get<RecentPanels>("/api/v1/dashboard/recent", signal),
  services: (signal?: AbortSignal) => get<ServiceHealth>("/api/v1/system/services", signal),
  sessions: (signal?: AbortSignal) => get<WhatsAppSessions>("/api/v1/whatsapp/sessions", signal),

  messages: (limit = 25, offset = 0, signal?: AbortSignal) =>
    get<MessageLogs>(`/api/v1/dashboard/messages?limit=${limit}&offset=${offset}`, signal),
  deleteMessage: (id: string) =>
    request<void>(`/api/v1/dashboard/messages/${id}`, { method: "DELETE" }),
  streamActivity,
}
