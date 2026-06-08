export type FactorKey = "technical" | "fundamental" | "capital" | "sentiment";

export interface AnalyzeRequest {
  query: string;
  selected_factors: FactorKey[];
  prompt_append?: Record<string, string>;
  trace?: boolean;
}

export interface UserIntent {
  stock_name: string;
  stock_code: string;
  intent_type: string;
  time_horizon: string;
  risk_preference: string;
  clarified_query: string;
}

export interface FactorEvidence {
  factor_name: string;
  trend_signal: string;
  score: number;
  key_findings: string[];
  risk_flags: string[];
  raw_data_summary: string;
}

export interface CompositeAssessment {
  composite_score: number;
  trend_direction: string;
  position_status: string;
  risk_level: string;
  risk_details: string[];
  summary: string;
}

export interface TraceEntry {
  node: string;
  node_label?: string;
  elapsed_ms?: number;
  timestamp?: string;
  status?: string;
  output_summary?: string;
}

export interface AnalyzeResponse {
  status: string;
  user_intent?: UserIntent | null;
  market_structure?: Record<string, unknown> | null;
  sector_route?: Record<string, unknown> | null;
  factors: {
    technical?: FactorEvidence | null;
    fundamental?: FactorEvidence | null;
    capital?: FactorEvidence | null;
    sentiment?: FactorEvidence | null;
  };
  composite_assessment?: CompositeAssessment | null;
  final_answer?: {
    answer: string;
    confidence: number;
    evidence_summary?: string;
    reasoning_trace?: string;
    timestamp?: string;
  } | null;
  evidence_log: EvidenceLogItem[];
  trace: TraceEntry[];
  charts?: {
    factor_scores?: FactorScore[];
    kline?: KlinePoint[];
    capital_flow?: Record<string, unknown>[];
    hot_stocks?: HotStock[];
  };
  error_message?: string | null;
}

export interface EvidenceLogItem {
  source?: string;
  score?: number;
  confidence?: number;
  content?: string;
  timestamp?: string;
  [key: string]: unknown;
}

export interface FactorScore {
  factor: FactorKey;
  label: string;
  score: number;
}

export interface KlinePoint {
  date: string;
  close: number | null;
  pct_change: number | null;
  volume: number | null;
}

export interface ChartDataResponse {
  stock_code: string;
  stock_name?: string;
  kline: KlinePoint[];
  valuation: Record<string, unknown>;
  basic?: Record<string, unknown>;
}

export interface HotStock {
  rank: number;
  code: string;
  name: string;
  market?: string;
  raw_code: string;
  pct_change?: number | null;
}
