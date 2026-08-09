/**
 * Gateway client.
 *
 * The Control Panel talks to the FastAPI gateway and to nothing else — never to
 * WAHA, Qdrant, Redis, PostgreSQL, or the ML Service
 * (08_Dashboard/01_Control_Panel_Overview.md §4). Every URL in this file starts
 * from NEXT_PUBLIC_API_URL for that reason: there is nowhere else to point it.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
const DASHBOARD_KEY = process.env.NEXT_PUBLIC_DASHBOARD_KEY ?? ""

export type RiskLevel = "HIGH" | "MEDIUM" | "LOW" | "UNKNOWN"

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

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const headers: HeadersInit = {}
  if (DASHBOARD_KEY) {
    headers["X-Dashboard-Key"] = DASHBOARD_KEY
  }

  let response: Response
  try {
    response = await fetch(`${API_URL}${path}`, {
      headers,
      signal,
      // Always live data: a cached security dashboard is a lying one.
      cache: "no-store",
    })
  } catch (error) {
    throw new GatewayError(error instanceof Error ? error.message : "gateway unreachable")
  }

  if (!response.ok) {
    throw new GatewayError(`gateway returned ${response.status}`, response.status)
  }

  return (await response.json()) as T
}

export const api = {
  summary: (signal?: AbortSignal) => get<DashboardSummary>("/api/v1/dashboard/summary", signal),
  activity: (limit = 15, signal?: AbortSignal) =>
    get<ActivityFeed>(`/api/v1/dashboard/activity?limit=${limit}`, signal),
  recent: (signal?: AbortSignal) => get<RecentPanels>("/api/v1/dashboard/recent", signal),
  services: (signal?: AbortSignal) => get<ServiceHealth>("/api/v1/system/services", signal),
  sessions: (signal?: AbortSignal) => get<WhatsAppSessions>("/api/v1/whatsapp/sessions", signal),
}
