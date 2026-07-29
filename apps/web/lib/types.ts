export type CoverageStatus = "setup" | "active" | "archived"

export interface Coverage {
  id: string
  ticker: string
  company_name: string
  exchange: string
  industry_id: string | null
  industry_name: string | null
  status: CoverageStatus
  document_count: number
  last_updated: string | null
  created_at: string
}

export interface Industry {
  id: string
  name: string
}

export interface Citation {
  doc: string
  section: string
  quote: string
}

export interface IndustryPrimer {
  id: string
  name: string
  primer_content: string | null
  primer_citations: Citation[]
  word_count: number | null
  llm_used: string | null
  updated_at: string | null
}

export interface IndustryAnalysisTaskResponse {
  industry_id: string
  task_id: string
  status: string
}

export const EXCHANGES = ["NYSE", "NASDAQ", "LSE", "TSX", "ASX", "Other"] as const
export type Exchange = (typeof EXCHANGES)[number]

// Backend `ingest_status` values. There is no "queued" state on the model —
// "pending" is what the UI presents as "Queued" (task enqueued, not yet running).
export type IngestStatus = "pending" | "indexing" | "indexed" | "failed" | "review_needed"

export const FILING_TYPES = [
  "10-K",
  "10-Q",
  "8-K",
  "Earnings Transcript",
  "Investor Day",
  "Custom",
] as const
export type FilingType = (typeof FILING_TYPES)[number]

export const SEC_FILING_TYPES = ["10-K", "10-Q", "8-K"] as const
export type SecFilingType = (typeof SEC_FILING_TYPES)[number]

export interface DocumentRow {
  id: string
  file_name: string
  filing_type: string
  period: string
  ingest_status: IngestStatus
  chunk_count: number
  quality_score: number | null
  ingested_at: string | null
}

export interface UploadTaskResponse {
  document_id: string
  task_id: string
  status: string
}

export type TaskStatus = "queued" | "running" | "completed" | "failed" | "cancelled"

export interface TaskRead {
  task_id: string
  status: TaskStatus
  started_at: string | null
  completed_at: string | null
  error: string | null
}

// --- KPI dashboard ------------------------------------------------------------

export type KpiCategory = "financial" | "operational"
export type KpiPeriodType = "annual" | "quarterly"

export interface KpiCitation {
  document_name?: string
  section?: string
  page_number?: number | null
  exact_quote?: string
  raw_value?: string
  [key: string]: unknown
}

export interface KpiDataPoint {
  period: string
  period_type: KpiPeriodType
  value: number
  unit: string
  is_restated: boolean
  restatement_note: string | null
  citation: KpiCitation
  yoy_change_pct: number | null
  extracted_at: string
}

export interface KpiSeries {
  kpi_name: string
  category: KpiCategory
  unit: string
  data_points: KpiDataPoint[]
}

export interface KpiListResponse {
  coverage_id: string
  kpis: KpiSeries[]
}

// --- Research outputs & streaming ---------------------------------------------

export type OutputType =
  | "industry_primer"
  | "lynch_pitch"
  | "munger_invert"
  | "quarterly_update"
  | "kpi_snapshot"

export type EnforcerStatus = "pending" | "approved" | "partial" | "failed"

export interface ResearchOutput {
  id: string
  coverage_id: string
  output_type: OutputType
  content: string
  citations: Citation[]
  citation_coverage_pct: number | null
  approved_by_enforcer: boolean
  enforcer_status: EnforcerStatus
  llm_used: string | null
  tokens_used: number
  generated_at: string
  approved_at: string | null
  version: number
  output_metadata: Record<string, unknown>
}

export interface RunAgentTaskResponse {
  task_id: string
  status: string
}

// Mirrors the event catalog StreamingService publishes over
// `/ws/tasks/{task_id}` (packages/shared/src/shared/streaming.py).
export interface ProgressEvent {
  type: "progress"
  step: string
  pct: number
  detail: string
}

export interface ChunkEvent {
  type: "chunk"
  content: string
  citations: Citation[]
}

export interface CitationFoundEvent {
  type: "citation_found"
  doc: string
  section: string
  quote: string
}

export interface EnforcerRunningEvent {
  type: "enforcer_running"
  attempt: number
}

export interface EnforcerResultEvent {
  type: "enforcer_result"
  approved: boolean
  citation_coverage_pct: number
}

export interface CompleteEvent {
  type: "complete"
  output_id: string
  citation_coverage_pct: number
  llm_used: string
}

export interface ErrorEvent {
  type: "error"
  code: string
  retry_count: number
  detail: string
}

export interface PartialEvent {
  type: "partial"
  output_id: string
  citation_coverage_pct: number
  reason: string
}

export interface AlreadyCompleteEvent {
  type: "already_complete"
  output_id: string | null
}

export type TaskStreamEvent =
  | ProgressEvent
  | ChunkEvent
  | CitationFoundEvent
  | EnforcerRunningEvent
  | EnforcerResultEvent
  | CompleteEvent
  | ErrorEvent
  | PartialEvent
  | AlreadyCompleteEvent

// --- Analyst notes --------------------------------------------------------

export interface CoverageNotes {
  coverage_id: string
  content: string
  updated_at: string | null
}

export interface CitationSearchResult {
  chunk_id: string
  document_name: string
  section: string
  quote: string
  score: number
}

// --- Notifications ---------------------------------------------------------

export type NotificationType = "earnings_complete"

export interface AppNotification {
  id: string
  type: NotificationType
  ticker: string
  coverage_id: string
  output_id: string
  timestamp: string
  read: boolean
}

// --- Admin usage -------------------------------------------------------------

export interface MonthlyCost {
  month: string
  cost_usd: number
}

export interface ModelUsage {
  llm_used: string
  tokens_used: number
  cost_usd: number
}

export interface CoverageUsageBreakdown {
  coverage_id: string
  ticker: string
  tokens_used: number
  cost_usd: number
}

export interface TenantUsage {
  tenant_id: string
  tenant_name: string
  monthly_costs: MonthlyCost[]
  by_model: ModelUsage[]
  by_coverage: CoverageUsageBreakdown[]
  alert_threshold_usd: number | null
}

export interface UsageResponse {
  tenants: TenantUsage[]
}
