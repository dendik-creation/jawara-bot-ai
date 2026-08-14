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

export type RecentAlertItem = {
  id: string
  at: string
  severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
  title: string
  source: string
  state: "NEW" | "ACKNOWLEDGED" | "RESOLVED" | "ESCALATED"
}

export type RecentIncidentItem = {
  id: string
  code: string
  at: string
  title: string
  severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
  state: "OPEN" | "INVESTIGATING" | "CONTAINED" | "RESOLVED" | "FALSE_POSITIVE"
}

export type RecentPanels = {
  threats: RecentBlock<ThreatItem>
  incidents: RecentBlock<RecentIncidentItem>
  alerts: RecentBlock<RecentAlertItem>
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

export type AuditResult = "SUCCESS" | "FAILED" | "DENIED"

export type AuditLogItem = {
  id: string
  at: string
  actor_operator_id: string | null
  actor_name: string | null
  action: string
  target_type: string
  target_id: string | null
  result: AuditResult
  metadata: Record<string, unknown>
  ip_address: string | null
}

export type AuditLog = {
  available: boolean
  reason?: string
  total: number
  items: AuditLogItem[]
}

export type AuditLogParams = {
  limit?: number
  offset?: number
  action?: string
  actorOperatorId?: string
  targetType?: string
  dateFrom?: string
  dateTo?: string
}

export type ThreatCategory =
  | "PHISHING"
  | "SCAM"
  | "SOCIAL_ENGINEERING"
  | "MALICIOUS_LINK"
  | "IMPERSONATION"
  | "SPAM"
  | "OTHER"

export type ThreatState = "DETECTED" | "ANALYZED" | "ACTIONED" | "RESOLVED"

export type ThreatActionValue = "ALLOW" | "WARN" | "BLOCK" | "ESCALATE" | "CONFIRM" | "FALSE_POSITIVE"

/** The full Threats-screen record — distinct from `ThreatItem` (RecentPanels' compact summary shape). */
export type ThreatRecord = {
  message_log_id: string
  at: string
  session: string
  chat_type: string
  user_hash: string
  intent: string | null
  threat_category: ThreatCategory
  risk: "HIGH" | "MEDIUM"
  similarity_score: number | null
  state: ThreatState
  action: ThreatActionValue | null
  action_by: string | null
  action_at: string | null
  notes: string | null
}

export type Threats = {
  available: boolean
  reason?: string
  total: number
  items: ThreatRecord[]
}

export type ThreatsParams = {
  limit?: number
  offset?: number
  severity?: "HIGH" | "MEDIUM"
  category?: ThreatCategory
  state?: ThreatState
  action?: ThreatActionValue
  userHash?: string
  dateFrom?: string
  dateTo?: string
}

export type AlertSeverity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
export type AlertState = "NEW" | "ACKNOWLEDGED" | "RESOLVED" | "ESCALATED"
export type AlertActionValue = "ACKNOWLEDGE" | "RESOLVE" | "ASSIGN_TO_ME"

export type AlertItem = {
  id: string
  severity: AlertSeverity
  title: string
  source: string
  source_threat_id: string | null
  state: AlertState
  assigned_operator_id: string | null
  assigned_operator_name: string | null
  resolution_reason: string | null
  created_at: string
  updated_at: string
}

export type Alerts = {
  available: boolean
  reason?: string
  total: number
  items: AlertItem[]
}

export type AlertsParams = {
  limit?: number
  offset?: number
  severity?: AlertSeverity
  state?: AlertState
  source?: string
  dateFrom?: string
  dateTo?: string
}

export type IncidentSeverity = AlertSeverity
export type IncidentState = "OPEN" | "INVESTIGATING" | "CONTAINED" | "RESOLVED" | "FALSE_POSITIVE"
export type IncidentActionValue = "ASSIGN_TO_ME" | "SET_STATE" | "SET_SEVERITY" | "CLOSE" | "ESCALATE"

export type IncidentSummary = {
  id: string
  code: string
  title: string
  severity: IncidentSeverity
  state: IncidentState
  assigned_operator_id: string | null
  assigned_operator_name: string | null
  resolution_reason: string | null
  created_by: string
  created_by_name: string
  created_at: string
  updated_at: string
  message_count: number
  affected_user_count: number
}

export type IncidentNote = {
  id: string
  note: string
  at: string
  author_operator_id: string
  author_name: string
}

export type IncidentDetail = IncidentSummary & {
  threats: ThreatRecord[]
  categories: string[]
  notes: IncidentNote[]
}

export type Incidents = {
  available: boolean
  reason?: string
  total: number
  items: IncidentSummary[]
}

export type IncidentsParams = {
  limit?: number
  offset?: number
  severity?: IncidentSeverity
  state?: IncidentState
  dateFrom?: string
  dateTo?: string
}

export type UserTier = "HIGH" | "MEDIUM" | "NONE"
export type UserChatType = "PERSONAL" | "GROUP"
export type UserActionValue = "BLOCK" | "UNBLOCK"

export type UserSummary = {
  user_hash: string
  chat_type: UserChatType
  is_active: boolean
  subscribed_at: string
  threat_count: number
  tier: UserTier
  score: number
  last_seen: string | null
  blocked: boolean
  block_reason: string | null
  blocked_by: string | null
  blocked_by_name: string | null
  blocked_at: string | null
}

export type UserDetail = UserSummary & {
  dominant_category: string | null
  recent_threats: ThreatRecord[]
}

export type Users = {
  available: boolean
  reason?: string
  total: number
  items: UserSummary[]
}

export type UsersParams = {
  limit?: number
  offset?: number
  tier?: UserTier
  chatType?: UserChatType
  isActive?: boolean
  blocked?: boolean
}

export type DetectionRuleType =
  | "KEYWORD"
  | "DOMAIN"
  | "URL"
  | "RISK_THRESHOLD"
  | "PATTERN"
  | "REPEATED_OFFENDER"
  | "RATE_LIMIT"
  | "ALLOWLIST"
  | "BLOCKLIST"
export type DetectionRuleSeverity = "HIGH" | "MEDIUM" | "LOW"
export type DetectionRuleStatus = "DRAFT" | "ACTIVE" | "DISABLED" | "ARCHIVED"
export type DetectionRuleActionValue = "UPDATE" | "ACTIVATE" | "DISABLE" | "ARCHIVE"

export type DetectionRuleItem = {
  id: string
  name: string
  rule_type: DetectionRuleType
  condition: Record<string, unknown>
  severity: DetectionRuleSeverity
  status: DetectionRuleStatus
  created_by: string
  created_by_name: string
  created_at: string
  updated_at: string
}

export type DetectionRules = {
  available: boolean
  reason?: string
  total: number
  items: DetectionRuleItem[]
}

export type DetectionRulesParams = {
  limit?: number
  offset?: number
  ruleType?: DetectionRuleType
  status?: DetectionRuleStatus
  severity?: DetectionRuleSeverity
}

export type PolicyScope = "DEFAULT" | "CATEGORY_THRESHOLD" | "USER_SPECIFIC"
export type PolicyAction = "ALLOW" | "WARN" | "BLOCK" | "ALERT" | "ESCALATE"
export type PolicyStatus = "DRAFT" | "ACTIVE" | "DISABLED" | "ARCHIVED"
// PATCH body's lifecycle-verb field — named `operation`, not `action`, since a
// policy's own domain field is already called `action` (see PolicyItem below).
export type PolicyOperationValue = "UPDATE" | "ACTIVATE" | "DISABLE" | "ARCHIVE"

export type PolicyItem = {
  id: string
  name: string
  scope: PolicyScope
  condition: Record<string, unknown>
  action: PolicyAction
  priority: number
  status: PolicyStatus
  created_by: string
  created_by_name: string
  created_at: string
  updated_at: string
}

export type Policies = {
  available: boolean
  reason?: string
  total: number
  items: PolicyItem[]
}

export type PoliciesParams = {
  limit?: number
  offset?: number
  scope?: PolicyScope
  status?: PolicyStatus
  action?: PolicyAction
}

export type FactCategory = "HEALTH_HOAX" | "FINANCIAL_FRAUD" | "GENERAL_NEWS" | "PHISHING_LINK" | "FILE_APK"
export type Verdict = "HOAX" | "FACT" | "MISLEADING" | "UNVERIFIED"
export type FactItemActionValue = "UPDATE" | "ACTIVATE" | "DEACTIVATE"

export type FactItem = {
  id: string
  source_id: number
  source_name: string | null
  category: FactCategory
  title: string
  claim_summary: string
  fact_explanation: string
  verdict: Verdict
  source_url: string
  is_active: boolean
  synced_at: string | null
  sync_error: string | null
  created_at: string
  updated_at: string
}

export type FactItems = {
  available: boolean
  reason?: string
  total: number
  items: FactItem[]
}

export type FactItemsParams = {
  limit?: number
  offset?: number
  category?: FactCategory
  verdict?: Verdict
  isActive?: boolean
  sourceId?: number
  search?: string
}

export type SyncResult = {
  total: number
  upserted: number
  failed: number
  rejected: { fact_item_id: string; missing?: string[] }[]
}

export type FactSource = {
  id: number
  name: string
  base_url: string
  is_trusted: boolean
  normalized_domain: string | null
  created_at: string | null
}

export type FactSources = {
  available: boolean
  reason?: string
  items: FactSource[]
}

export type ImportCsvResult = {
  total: number
  created: number
  failed: number
  errors: { row: number; reason: string }[]
}

export type UnavailableBlock = { available: false; reason: string }

export type FeedbackType = "CONFIRM" | "FALSE_POSITIVE"

export type FeedbackItem = {
  id: string
  message_log_id: string
  original_classification: FactCategory | null
  feedback_type: FeedbackType
  model_version: string | null
  reason: string | null
  actor_operator_id: string
  actor_name: string
  created_at: string
  extracted_text: string | null
  current_intent: FactCategory | null
  risk_score: string
  used_in_dataset_id: string | null
  used_in_dataset_name: string | null
}

export type Feedback = {
  available: boolean
  reason?: string
  total: number
  items: FeedbackItem[]
}

export type FeedbackParams = {
  limit?: number
  offset?: number
  feedbackType?: FeedbackType
}

export type DatasetSource = "CURATED" | "OPERATOR_FEEDBACK" | "IMPORTED" | "APPROVED_INTERNAL"
export type DatasetStatus = "DRAFT" | "VALIDATING" | "VALIDATED" | "REJECTED" | "ARCHIVED"
export type DatasetActionValue = "UPDATE" | "VALIDATE" | "ARCHIVE"

export type DatasetItem = {
  id: string
  name: string
  version: number
  source: DatasetSource
  status: DatasetStatus
  description: string | null
  validation_notes: string | null
  created_by: string
  created_by_name: string
  created_at: string
  updated_at: string
  sample_count: number
}

export type DatasetSample = {
  id: string
  dataset_id: string
  text: string
  label: string
  source_message_log_id: string | null
  source_feedback_id: string | null
  added_by: string
  added_at: string
}

export type DatasetDetail = DatasetItem & {
  samples: DatasetSample[]
  label_counts: Record<string, number>
}

export type Datasets = {
  available: boolean
  reason?: string
  total: number
  items: DatasetItem[]
}

export type DatasetsParams = {
  limit?: number
  offset?: number
  status?: DatasetStatus
}

export type TrainingJobStatus = "QUEUED" | "RUNNING" | "EVALUATING" | "COMPLETED" | "FAILED" | "CANCELLED"
export type TrainingJobActionValue = "CANCEL"

export type TrainingJobItem = {
  id: string
  dataset_id: string
  dataset_name: string
  dataset_version: number
  base_model: string
  epochs: number | null
  learning_rate: number | null
  batch_size: number | null
  validation_split: number | null
  extra_config: Record<string, unknown> | null
  status: TrainingJobStatus
  progress: number | null
  metrics: Record<string, unknown> | null
  error_message: string | null
  generated_model_version: string | null
  celery_task_id: string | null
  started_at: string | null
  finished_at: string | null
  created_by: string
  created_by_name: string
  created_at: string
  updated_at: string
}

export type TrainingJobs = {
  available: boolean
  reason?: string
  total: number
  items: TrainingJobItem[]
}

export type TrainingJobsParams = {
  limit?: number
  offset?: number
  status?: TrainingJobStatus
}

export type ModelEvaluationStatus = "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED"
export type ModelEvaluationActionValue = "CANCEL"

export type ModelEvaluationItem = {
  id: string
  training_job_id: string
  training_job_base_model: string
  generated_model_version: string | null
  dataset_id: string
  dataset_name: string
  dataset_version: number
  status: ModelEvaluationStatus
  progress: number | null
  metrics: Record<string, unknown> | null
  error_message: string | null
  celery_task_id: string | null
  started_at: string | null
  finished_at: string | null
  created_by: string
  created_by_name: string
  created_at: string
  updated_at: string
}

export type ModelEvaluations = {
  available: boolean
  reason?: string
  total: number
  items: ModelEvaluationItem[]
}

export type ModelEvaluationsParams = {
  limit?: number
  offset?: number
  status?: ModelEvaluationStatus
}

export type ModelVersionStatus = "CANDIDATE" | "VALIDATED" | "PRODUCTION" | "ARCHIVED"
export type ModelVersionActionValue = "VALIDATE" | "PROMOTE" | "ARCHIVE"

export type ModelVersionItem = {
  id: string
  training_job_id: string
  training_job_base_model: string
  generated_model_version: string | null
  training_dataset_name: string
  training_dataset_version: number
  model_evaluation_id: string
  evaluation_metrics: Record<string, unknown> | null
  evaluation_dataset_name: string
  evaluation_dataset_version: number
  status: ModelVersionStatus
  created_at: string
  updated_at: string
}

export type ModelVersions = {
  available: boolean
  reason?: string
  total: number
  items: ModelVersionItem[]
}

export type ModelVersionsParams = {
  limit?: number
  offset?: number
  status?: ModelVersionStatus
}

export type AiMlOverview = {
  knowledge_base:
    | (UnavailableBlock)
    | {
        available: true
        total_facts: number
        active_facts: number
        synced: number
        never_synced: number
        sync_failed: number
        total_sources: number
      }
  detection_rules: UnavailableBlock | { available: true; total: number; by_status: Record<string, number> }
  policies: UnavailableBlock | { available: true; total: number; by_status: Record<string, number> }
  datasets: UnavailableBlock | { available: true; total: number; by_status: Record<string, number> }
  feedback: UnavailableBlock | { available: true; total: number; by_type: Record<string, number> }
  ml_service:
    | UnavailableBlock
    | {
        available: true
        status: string
        embedder: string | null
        llm: string | null
        degraded_reasons: string[]
        vector_store:
          | UnavailableBlock
          | { available: true; collection: string; points_count: number; vector_size: number; distance: string }
      }
  training_jobs: UnavailableBlock | { available: true; total: number; by_status: Record<string, number> }
  model_registry: UnavailableBlock | { available: true; total: number; by_status: Record<string, number> }
  evaluation: UnavailableBlock | { available: true; total: number; by_status: Record<string, number> }
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
    method?: "GET" | "POST" | "PATCH" | "DELETE"
    body?: unknown
    signal?: AbortSignal
    auth?: boolean
  } = {},
): Promise<T> {
  const isFormData = body instanceof FormData
  const headers: Record<string, string> = {}
  // FormData: the browser sets its own multipart boundary — an explicit
  // Content-Type here would strip it and break the upload.
  if (body !== undefined && !isFormData) headers["Content-Type"] = "application/json"

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
      body: body === undefined ? undefined : isFormData ? body : JSON.stringify(body),
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
  updateProfile: (fullName: string) =>
    request<Operator>("/api/v1/auth/me", {
      method: "PATCH",
      body: { full_name: fullName },
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

  auditLog: (params: AuditLogParams = {}, signal?: AbortSignal) => {
    const query = new URLSearchParams()
    query.set("limit", String(params.limit ?? 25))
    query.set("offset", String(params.offset ?? 0))
    if (params.action) query.set("action", params.action)
    if (params.actorOperatorId) query.set("actor_operator_id", params.actorOperatorId)
    if (params.targetType) query.set("target_type", params.targetType)
    if (params.dateFrom) query.set("date_from", params.dateFrom)
    if (params.dateTo) query.set("date_to", params.dateTo)
    return get<AuditLog>(`/api/v1/audit-log?${query.toString()}`, signal)
  },

  threats: (params: ThreatsParams = {}, signal?: AbortSignal) => {
    const query = new URLSearchParams()
    query.set("limit", String(params.limit ?? 25))
    query.set("offset", String(params.offset ?? 0))
    if (params.severity) query.set("severity", params.severity)
    if (params.category) query.set("category", params.category)
    if (params.state) query.set("state", params.state)
    if (params.action) query.set("action", params.action)
    if (params.userHash) query.set("user_hash", params.userHash)
    if (params.dateFrom) query.set("date_from", params.dateFrom)
    if (params.dateTo) query.set("date_to", params.dateTo)
    return get<Threats>(`/api/v1/threats?${query.toString()}`, signal)
  },
  actionOnThreat: (messageLogId: string, action: ThreatActionValue, notes?: string) =>
    request<ThreatRecord>(`/api/v1/threats/${messageLogId}`, {
      method: "PATCH",
      body: { action, notes: notes || undefined },
    }),

  alerts: (params: AlertsParams = {}, signal?: AbortSignal) => {
    const query = new URLSearchParams()
    query.set("limit", String(params.limit ?? 25))
    query.set("offset", String(params.offset ?? 0))
    if (params.severity) query.set("severity", params.severity)
    if (params.state) query.set("state", params.state)
    if (params.source) query.set("source", params.source)
    if (params.dateFrom) query.set("date_from", params.dateFrom)
    if (params.dateTo) query.set("date_to", params.dateTo)
    return get<Alerts>(`/api/v1/alerts?${query.toString()}`, signal)
  },
  actionOnAlert: (alertId: string, action: AlertActionValue, reason?: string) =>
    request<AlertItem>(`/api/v1/alerts/${alertId}`, {
      method: "PATCH",
      body: { action, reason: reason || undefined },
    }),

  incidents: (params: IncidentsParams = {}, signal?: AbortSignal) => {
    const query = new URLSearchParams()
    query.set("limit", String(params.limit ?? 25))
    query.set("offset", String(params.offset ?? 0))
    if (params.severity) query.set("severity", params.severity)
    if (params.state) query.set("state", params.state)
    if (params.dateFrom) query.set("date_from", params.dateFrom)
    if (params.dateTo) query.set("date_to", params.dateTo)
    return get<Incidents>(`/api/v1/incidents?${query.toString()}`, signal)
  },
  incident: (id: string, signal?: AbortSignal) => get<IncidentDetail>(`/api/v1/incidents/${id}`, signal),
  createIncident: (title: string, severity: IncidentSeverity, messageLogIds: string[]) =>
    request<IncidentDetail>("/api/v1/incidents", {
      method: "POST",
      body: { title, severity, message_log_ids: messageLogIds },
    }),
  addThreatToIncident: (incidentId: string, messageLogId: string) =>
    request<IncidentDetail>(`/api/v1/incidents/${incidentId}/threats`, {
      method: "POST",
      body: { message_log_id: messageLogId },
    }),
  removeThreatFromIncident: (incidentId: string, messageLogId: string) =>
    request<IncidentDetail>(`/api/v1/incidents/${incidentId}/threats/${messageLogId}`, { method: "DELETE" }),
  addIncidentNote: (incidentId: string, note: string) =>
    request<IncidentDetail>(`/api/v1/incidents/${incidentId}/notes`, {
      method: "POST",
      body: { note },
    }),
  actionOnIncident: (
    incidentId: string,
    action: IncidentActionValue,
    opts: { state?: IncidentState; severity?: IncidentSeverity; reason?: string } = {},
  ) =>
    request<IncidentDetail>(`/api/v1/incidents/${incidentId}`, {
      method: "PATCH",
      body: { action, ...opts },
    }),

  users: (params: UsersParams = {}, signal?: AbortSignal) => {
    const query = new URLSearchParams()
    query.set("limit", String(params.limit ?? 25))
    query.set("offset", String(params.offset ?? 0))
    if (params.tier) query.set("tier", params.tier)
    if (params.chatType) query.set("chat_type", params.chatType)
    if (params.isActive !== undefined) query.set("is_active", String(params.isActive))
    if (params.blocked !== undefined) query.set("blocked", String(params.blocked))
    return get<Users>(`/api/v1/users?${query.toString()}`, signal)
  },
  user: (userHash: string, signal?: AbortSignal) => get<UserDetail>(`/api/v1/users/${userHash}`, signal),
  actionOnUser: (userHash: string, action: UserActionValue, reason: string) =>
    request<UserDetail>(`/api/v1/users/${userHash}`, {
      method: "PATCH",
      body: { action, reason },
    }),

  detectionRules: (params: DetectionRulesParams = {}, signal?: AbortSignal) => {
    const query = new URLSearchParams()
    query.set("limit", String(params.limit ?? 25))
    query.set("offset", String(params.offset ?? 0))
    if (params.ruleType) query.set("rule_type", params.ruleType)
    if (params.status) query.set("status", params.status)
    if (params.severity) query.set("severity", params.severity)
    return get<DetectionRules>(`/api/v1/detection-rules?${query.toString()}`, signal)
  },
  createDetectionRule: (
    name: string,
    ruleType: DetectionRuleType,
    condition: Record<string, unknown>,
    severity: DetectionRuleSeverity,
  ) =>
    request<DetectionRuleItem>("/api/v1/detection-rules", {
      method: "POST",
      body: { name, rule_type: ruleType, condition, severity },
    }),
  actionOnDetectionRule: (
    ruleId: string,
    action: DetectionRuleActionValue,
    opts: { name?: string; condition?: Record<string, unknown>; severity?: DetectionRuleSeverity } = {},
  ) =>
    request<DetectionRuleItem>(`/api/v1/detection-rules/${ruleId}`, {
      method: "PATCH",
      body: { action, ...opts },
    }),

  policies: (params: PoliciesParams = {}, signal?: AbortSignal) => {
    const query = new URLSearchParams()
    query.set("limit", String(params.limit ?? 25))
    query.set("offset", String(params.offset ?? 0))
    if (params.scope) query.set("scope", params.scope)
    if (params.status) query.set("status", params.status)
    if (params.action) query.set("action", params.action)
    return get<Policies>(`/api/v1/policies?${query.toString()}`, signal)
  },
  createPolicy: (
    name: string,
    scope: PolicyScope,
    condition: Record<string, unknown>,
    action: PolicyAction,
    priority?: number,
  ) =>
    request<PolicyItem>("/api/v1/policies", {
      method: "POST",
      body: { name, scope, condition, action, priority },
    }),
  actionOnPolicy: (
    policyId: string,
    operation: PolicyOperationValue,
    opts: { name?: string; condition?: Record<string, unknown>; action?: PolicyAction; priority?: number } = {},
  ) =>
    request<PolicyItem>(`/api/v1/policies/${policyId}`, {
      method: "PATCH",
      body: { operation, ...opts },
    }),

  factItems: (params: FactItemsParams = {}, signal?: AbortSignal) => {
    const query = new URLSearchParams()
    query.set("limit", String(params.limit ?? 25))
    query.set("offset", String(params.offset ?? 0))
    if (params.category) query.set("category", params.category)
    if (params.verdict) query.set("verdict", params.verdict)
    if (params.isActive !== undefined) query.set("is_active", String(params.isActive))
    if (params.sourceId !== undefined) query.set("source_id", String(params.sourceId))
    if (params.search) query.set("search", params.search)
    return get<FactItems>(`/api/v1/knowledge/facts?${query.toString()}`, signal)
  },
  factItem: (id: string, signal?: AbortSignal) => get<FactItem>(`/api/v1/knowledge/facts/${id}`, signal),
  createFactItem: (
    sourceId: number,
    category: FactCategory,
    title: string,
    claimSummary: string,
    factExplanation: string,
    verdict: Verdict,
    sourceUrl: string,
  ) =>
    request<FactItem>("/api/v1/knowledge/facts", {
      method: "POST",
      body: {
        source_id: sourceId,
        category,
        title,
        claim_summary: claimSummary,
        fact_explanation: factExplanation,
        verdict,
        source_url: sourceUrl,
      },
    }),
  actionOnFactItem: (
    id: string,
    action: FactItemActionValue,
    opts: {
      category?: FactCategory
      title?: string
      claim_summary?: string
      fact_explanation?: string
      verdict?: Verdict
      source_url?: string
    } = {},
  ) =>
    request<FactItem>(`/api/v1/knowledge/facts/${id}`, {
      method: "PATCH",
      body: { action, ...opts },
    }),
  syncFactItem: (id: string) => request<SyncResult>(`/api/v1/knowledge/facts/${id}/sync`, { method: "POST" }),
  syncAllFactItems: () => request<SyncResult>("/api/v1/knowledge/facts/sync-all", { method: "POST" }),

  factSources: (signal?: AbortSignal) => get<FactSources>("/api/v1/knowledge/sources", signal),
  createFactSource: (name: string, baseUrl: string, isTrusted: boolean) =>
    request<FactSource>("/api/v1/knowledge/sources", {
      method: "POST",
      body: { name, base_url: baseUrl, is_trusted: isTrusted },
    }),
  updateFactSource: (
    id: number,
    opts: { isTrusted?: boolean; reliabilityScore?: number; resync?: boolean },
  ) =>
    request<FactSource & { previous_reliability?: number; stale_in_qdrant?: number; resync?: unknown }>(
      `/api/v1/knowledge/sources/${id}`,
      {
        method: "PATCH",
        body: {
          is_trusted: opts.isTrusted,
          reliability_score: opts.reliabilityScore,
          resync: opts.resync,
        },
      },
    ),

  importFactItemsCsv: (file: File) => {
    const form = new FormData()
    form.set("file", file)
    return request<ImportCsvResult>("/api/v1/knowledge/facts/import-csv", { method: "POST", body: form })
  },

  aiMlOverview: (signal?: AbortSignal) => get<AiMlOverview>("/api/v1/ai-ml/overview", signal),

  feedback: (params: FeedbackParams = {}, signal?: AbortSignal) => {
    const query = new URLSearchParams()
    query.set("limit", String(params.limit ?? 25))
    query.set("offset", String(params.offset ?? 0))
    if (params.feedbackType) query.set("feedback_type", params.feedbackType)
    return get<Feedback>(`/api/v1/feedback?${query.toString()}`, signal)
  },

  datasets: (params: DatasetsParams = {}, signal?: AbortSignal) => {
    const query = new URLSearchParams()
    query.set("limit", String(params.limit ?? 25))
    query.set("offset", String(params.offset ?? 0))
    if (params.status) query.set("status", params.status)
    return get<Datasets>(`/api/v1/datasets?${query.toString()}`, signal)
  },
  dataset: (id: string, signal?: AbortSignal) => get<DatasetDetail>(`/api/v1/datasets/${id}`, signal),
  createDataset: (name: string, version: number, source: DatasetSource, description?: string) =>
    request<DatasetItem>("/api/v1/datasets", { method: "POST", body: { name, version, source, description } }),
  actionOnDataset: (id: string, action: DatasetActionValue, opts: { name?: string; description?: string } = {}) =>
    request<DatasetItem>(`/api/v1/datasets/${id}`, { method: "PATCH", body: { action, ...opts } }),
  addDatasetSample: (
    datasetId: string,
    text: string,
    label: string,
    opts: { sourceMessageLogId?: string; sourceFeedbackId?: string } = {},
  ) =>
    request<DatasetSample>(`/api/v1/datasets/${datasetId}/samples`, {
      method: "POST",
      body: {
        text,
        label,
        source_message_log_id: opts.sourceMessageLogId,
        source_feedback_id: opts.sourceFeedbackId,
      },
    }),
  removeDatasetSample: (datasetId: string, sampleId: string) =>
    request<{ removed: boolean }>(`/api/v1/datasets/${datasetId}/samples/${sampleId}`, { method: "DELETE" }),

  trainingJobs: (params: TrainingJobsParams = {}, signal?: AbortSignal) => {
    const query = new URLSearchParams()
    query.set("limit", String(params.limit ?? 25))
    query.set("offset", String(params.offset ?? 0))
    if (params.status) query.set("status", params.status)
    return get<TrainingJobs>(`/api/v1/training-jobs?${query.toString()}`, signal)
  },
  trainingJob: (id: string, signal?: AbortSignal) => get<TrainingJobItem>(`/api/v1/training-jobs/${id}`, signal),
  createTrainingJob: (
    datasetId: string,
    baseModel: string,
    opts: {
      epochs?: number
      learningRate?: number
      batchSize?: number
      validationSplit?: number
      extraConfig?: Record<string, unknown>
    } = {},
  ) =>
    request<TrainingJobItem>("/api/v1/training-jobs", {
      method: "POST",
      body: {
        dataset_id: datasetId,
        base_model: baseModel,
        epochs: opts.epochs,
        learning_rate: opts.learningRate,
        batch_size: opts.batchSize,
        validation_split: opts.validationSplit,
        extra_config: opts.extraConfig,
      },
    }),
  actionOnTrainingJob: (id: string, action: TrainingJobActionValue) =>
    request<TrainingJobItem>(`/api/v1/training-jobs/${id}`, { method: "PATCH", body: { action } }),

  modelEvaluations: (params: ModelEvaluationsParams = {}, signal?: AbortSignal) => {
    const query = new URLSearchParams()
    query.set("limit", String(params.limit ?? 25))
    query.set("offset", String(params.offset ?? 0))
    if (params.status) query.set("status", params.status)
    return get<ModelEvaluations>(`/api/v1/model-evaluations?${query.toString()}`, signal)
  },
  modelEvaluation: (id: string, signal?: AbortSignal) =>
    get<ModelEvaluationItem>(`/api/v1/model-evaluations/${id}`, signal),
  createModelEvaluation: (trainingJobId: string, datasetId: string) =>
    request<ModelEvaluationItem>("/api/v1/model-evaluations", {
      method: "POST",
      body: { training_job_id: trainingJobId, dataset_id: datasetId },
    }),
  actionOnModelEvaluation: (id: string, action: ModelEvaluationActionValue) =>
    request<ModelEvaluationItem>(`/api/v1/model-evaluations/${id}`, { method: "PATCH", body: { action } }),

  modelVersions: (params: ModelVersionsParams = {}, signal?: AbortSignal) => {
    const query = new URLSearchParams()
    query.set("limit", String(params.limit ?? 25))
    query.set("offset", String(params.offset ?? 0))
    if (params.status) query.set("status", params.status)
    return get<ModelVersions>(`/api/v1/model-versions?${query.toString()}`, signal)
  },
  modelVersion: (id: string, signal?: AbortSignal) => get<ModelVersionItem>(`/api/v1/model-versions/${id}`, signal),
  actionOnModelVersion: (id: string, action: ModelVersionActionValue) =>
    request<ModelVersionItem>(`/api/v1/model-versions/${id}`, { method: "PATCH", body: { action } }),
}
