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
