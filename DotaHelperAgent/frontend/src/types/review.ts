/**
 * 赛后复盘相关类型定义
 *
 * 与后端 `post_match_review.domain_types` 字段保持一致
 */

export type ImpactLevel = 'high' | 'medium' | 'low'

export type ProgressEventType =
  | 'phase_start'
  | 'phase_complete'
  | 'progress'
  | 'report'
  | 'error'

export type ReviewStatus = 'idle' | 'analyzing' | 'completed' | 'error' | 'interrupted'

export interface Conclusion {
  title: string
  content: string
  evidence: string[]
  has_evidence: boolean
  impact: ImpactLevel
  suggestion?: string
}

export interface AnalysisResult {
  phase: string
  conclusions: Conclusion[]
  confidence: number
  iterations_used: number
  tokens_consumed: number
  analysis_text: string
}

export interface MatchSummary {
  match_id: string
  duration: number
  radiant_win: boolean
  radiant_score: number
  dire_score: number
  user_hero: string
  user_team_win: boolean
  key_events: string[]
}

export interface ReviewReport {
  match_id: string
  match_summary: MatchSummary
  phase_results: AnalysisResult[]
  overall_score: number
  overall_confidence: number
  key_findings: string[]
  improvement_areas: string[]
  markdown_report: string
  terminal_state: string
  created_at: string
}

export interface ProgressEvent {
  event: ProgressEventType
  phase?: string
  progress: number
  message: string
  payload: Record<string, unknown>
}

export interface ReviewStateSnapshot {
  match_id: string
  status: ReviewStatus
  progress: number
  currentPhase?: string
  errorMessage?: string
}

export interface ReviewHistoryItem {
  match_id: string
  status: ReviewStatus | string
  overall_score: number
  overall_confidence: number
  terminal_state: string
  created_at: string
  completed_at?: string
}

export interface ReviewStatusResponse {
  success: boolean
  status?: ReviewStateSnapshot
  error?: string
}

export interface ReviewReportResponse {
  success: boolean
  report?: ReviewReport
  error?: string
}

export interface ReviewHistoryResponse {
  success: boolean
  history: ReviewHistoryItem[]
}

export interface InterruptReviewResponse {
  success: boolean
  result: {
    match_id: string
    success: boolean
    status: string
  }
}
