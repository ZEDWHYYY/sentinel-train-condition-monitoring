export type Subsystem = "door" | "acv" | "rail" | "shm";

export const SUBSYSTEM_NAMES: Record<Subsystem, string> = {
  door: "Door",
  acv: "ACV (air conditioning)",
  rail: "Rail corrugation",
  shm: "Structural health (SHM)",
};

export type SubsystemInfo = {
  id: Subsystem;
  label: string;
  task: string;
  formats: string;
  model: { available: boolean; version?: string; method?: string; reason?: string };
};

export type Recognition = {
  path: "recognized" | "needs_confirmation" | "exploration" | "unreadable";
  subsystem: Subsystem | null;
  reason?: string;
  suggestion?: string;
  confidence?: string;
  conflict?: string;
  needs?: { question: string; field: "sheet" | "subsystem"; options: string[] } | null;
  preview?: Record<string, unknown>;
  sheets?: { sheet: string; cars: string[]; columns: number; compatible: boolean }[];
};

export type RunFile = {
  id: string;
  original_name: string;
  sha256: string;
  size: number;
  source_kind: "upload" | "local_path";
  subsystem: Subsystem | null;
  recognition: Recognition | null;
  sheet: string | null;
  status: "ready" | "awaiting_input" | "exploration_only" | "unreadable" | "analyzed" | "failed";
  error: { code: string; message: string; suggestion?: string } | null;
  repeats?: { id: string; run_id: string; created: string }[];
  result?: ResultSummary | null;
};

export type RunState =
  | "draft"
  | "queued"
  | "running"
  | "completed"
  | "partial_failure"
  | "failed"
  | "cancelled"
  | "interrupted";

export type Run = {
  id: string;
  subsystem: Subsystem | null;
  subsystem_label: string;
  state: RunState;
  created: string;
  updated: string;
  stage: string | null;
  files_done: number;
  files_total: number;
  error: { code: string; message: string } | null;
  versions: { parser: string; features: string; model: string | null; policy: string } | null;
  files: RunFile[];
  siblings: { id: string; subsystem: Subsystem; state: RunState }[];
  review_total: number;
  label?: string | null;
};

export type ResultSummary = {
  id: string;
  file_id: string;
  available: number | boolean;
  headline: string;
  review_count: number;
  quality_state: string;
  model_version: string;
  repeat_of: string | null;
};

export type ReviewReason = { code: string; message: string; next_check: string; evidence_ref?: string };

export type Item = {
  id: string;
  prediction: string | number | null;
  review_reasons: ReviewReason[];
  evidence_state: string;
  observations: string[];
  triage?: Triage;
  [k: string]: unknown;
};

export type QualityIssue = {
  code: string;
  severity: "info" | "warning" | "blocking";
  description: string;
  scope: string;
  treatment: string;
  effect: string;
  next_step: string;
};

export type ResultRow = {
  id: string;
  file: { id: string; original_name: string; sha256: string; size: number };
  available: boolean;
  headline: string;
  review_count: number;
  quality_state: string;
  model_version: string;
  repeat_of: string | null;
  items: Item[];
  summary: Record<string, unknown>;
  issues: QualityIssue[];
  assessments?: Record<string, string>;
  statuses?: Record<string, string>;
  operator_summary?: OperatorSummary;
};

export type Series = {
  name: string;
  role: "primary" | "reference" | "band" | "secondary";
  x: (number | string)[];
  min?: (number | null)[];
  max?: (number | null)[];
  y?: (number | null)[];
  i0?: number[];
  i1?: number[];
  aggregated?: boolean;
  labels?: string[];
};

export type ChartBand = { x0: number; x1: number; label?: string; tone?: string; review?: boolean; id?: string };

export type Chart = {
  kind: "line" | "bar" | "grouped_bar" | "timeline";
  title: string;
  signal: string;
  unit: string;
  x_label: string;
  source: string;
  state: string;
  reference: string | null;
  series: Series[];
  markers: { x: number; label: string }[];
  bands: ChartBand[];
  caption: string;
};

export type ReviewEntry = {
  id: string;
  result_id: string;
  item_id: string;
  kind: "review" | "priority" | "status";
  assessment: string;
  note: string | null;
  reviewer: string | null;
  reason: string | null;
  assignee?: string | null;
  due?: string | null;
  revision: number;
  created: string;
};

export type FullResult = {
  id: string;
  run_id: string;
  subsystem: Subsystem;
  repeat_of: string | null;
  file: { id: string; original_name: string; sha256: string; size: number; sheet: string | null; source_kind: string };
  payload: {
    task: Subsystem;
    headline: string;
    available: boolean;
    unavailable_reason?: string;
    items: Item[];
    summary: Record<string, unknown>;
    overview_chart?: Chart;
    profile: Record<string, unknown> & { rows: number; columns: number; coverage: string; sample_rate_hz: number | null; sample_rate_source: string };
    issues: QualityIssue[];
    model_version: string;
    method_name: string;
    quality_state: string;
    recording_context?: Record<string, string | boolean>;
  };
  reviews: ReviewEntry[];
  created: string;
  asset_label?: string | null;
};

export const ASSESSMENT_LABELS: Record<string, string> = {
  agrees: "Agrees with prediction",
  disagrees: "Disagrees with prediction",
  needs_more_evidence: "Needs more evidence",
  leave_for_later: "Left for later",
  note: "Note added",
};

export const PRIORITY_LABELS: Record<string, string> = {
  unassessed: "Priority unassessed",
  planned_review: "Planned review (moderate)",
  urgent_assessment: "Urgent assessment (critical)",
};

// ---------------------------------------------------------------- Part 2: triage, lifecycle, attention
export type Severity = "high" | "medium" | "low" | "info";

export const SEVERITY_META: Record<Severity, { label: string; cls: string; rank: number; hint: string }> = {
  high: { label: "Act now", cls: "sev-high", rank: 0, hint: "Clear evidence of a fault; arrange a check at the next opportunity." },
  medium: { label: "Plan a check", cls: "sev-medium", rank: 1, hint: "Probable or competing evidence; put it on the next planned visit." },
  low: { label: "Watch", cls: "sev-low", rank: 2, hint: "Uncertain or weak evidence; keep an eye on it, re-check on the next recording." },
  info: { label: "Information", cls: "sev-info", rank: 3, hint: "Consistent with normal operation." },
};

export type Triage = {
  severity: Severity;
  severity_label: string;
  what: string;
  where: string;
  how_sure: string;
  action: string;
  next_check: string;
  detail: string;
  review_count: number;
  policy_version: string;
  policy_illustrative: boolean;
  strength?: number;
  heat?: { cars: number[]; side_I: number[]; side_II: number[]; unit: string; predicted_side: string | null };
};

export type InvestigationStatus = "open" | "acknowledged" | "investigating" | "confirmed" | "not_found" | "closed";

export const STATUS_LABELS: Record<string, string> = {
  open: "Open",
  acknowledged: "Acknowledged",
  investigating: "Investigating",
  confirmed: "Outcome: fault confirmed",
  not_found: "Outcome: nothing found",
  closed: "Closed",
};

export type OperatorSummary = { text: string; top_severity: Severity; counts: Record<Severity, number> };

export type AttentionCard = Triage & {
  result_id: string;
  run_id: string;
  item_id: string;
  subsystem: Subsystem;
  file: string | null;
  asset_label: string | null;
  analysed: string;
  prediction: string | number | null;
  status: InvestigationStatus;
  status_label: string;
  assignee?: string | null;
  due?: string | null;
  status_by?: string | null;
  priority: string;
  priority_by: string | null;
  priority_reason: string | null;
  last_note: string | null;
  recording_context?: Record<string, string | boolean>;
};

export type TriagePolicy = {
  version: string;
  illustrative: boolean;
  note: string;
  door: Record<string, string | number>;
  acv: Record<string, string | number>;
  rail: Record<string, string | number>;
  shm: Record<string, string | number>;
};
