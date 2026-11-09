/** Response shapes from the FastAPI backend (mirrors backend/app/models.py and routes). */

export type RunStatus =
  | 'queued'
  | 'running'
  | 'awaiting_review'
  | 'creating_tickets'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type TicketType = 'Story' | 'Task' | 'Bug' | 'Sub-task';
export type Confidence = 'high' | 'medium' | 'low';

export interface RunInputs {
  repo: string;
  branch: string;
  jira_project_key: string;
  issue_types: TicketType[];
  sprint_id: number | null;
}

export interface Run {
  id: string;
  status: RunStatus;
  inputs: RunInputs;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface RunEvent {
  id: number;
  run_id: string;
  ts: string;
  step: string;
  level: 'info' | 'warning' | 'error';
  message: string;
}

export interface ScreenSummary {
  screen: string;
  feedback: string[];
  decisions: string[];
  actions: string[];
  open_questions: string[];
}

export interface MeetingAnalysis {
  screens: ScreenSummary[];
  parked: string[];
  notes: string[];
}

export interface Requirement {
  id: string;
  title: string;
  detail: string;
  screen: string | null;
  source_quote: string | null;
  priority_hint: 'high' | 'medium' | 'low' | null;
}

export interface Evidence {
  path: string;
  start_line: number | null;
  end_line: number | null;
  note: string;
}

export interface CodeFinding {
  requirement_id: string;
  status: 'implemented' | 'partial' | 'missing' | 'unclear';
  evidence: Evidence[];
  affected_files: string[];
  confidence: Confidence;
}

export interface TicketDraft {
  temp_id: string;
  type: TicketType;
  title: string;
  description: string;
  acceptance_criteria: string[];
  estimate: string | null;
  labels: string[];
  related_files: string[];
  requirement_ids: string[];
  status_in_code: 'new' | 'extends_existing' | 'already_done';
  selected: boolean;
}

export interface DraftView {
  draft: TicketDraft;
  edited: boolean;
  jira_key: string | null;
  jira_url: string | null;
}

export interface CreatedTicket {
  temp_id: string;
  key: string | null;
  url: string | null;
  existed: boolean;
  error: string | null;
}

export interface RunDetail {
  run: Run;
  transcript_title: string | null;
  screenshots: { order: number; caption: string | null; url: string }[];
  meeting_analysis: MeetingAnalysis | null;
  requirements: Requirement[];
  code_findings: CodeFinding[];
  files_read: string[];
  drafts: DraftView[];
  created: CreatedTicket[];
  tokens_used: number;
  jira_labels: string[];
}

export interface Repo {
  id: string;
  name: string;
  default_branch: string | null;
}

export interface JiraProject {
  key: string;
  name: string;
}

export interface JiraIssueType {
  id: string;
  name: string;
  subtask: boolean;
}

export interface Estimate {
  tokens: number;
  max_tokens_per_run: number;
}

export interface ConfigStatus {
  llm: {
    provider: 'anthropic' | 'fake';
    model: string;
    api_key_set: boolean;
    max_tokens_per_run: number;
  };
  code: { provider: 'github' | 'gitlab' | 'fake'; base_url: string | null };
  jira: { provider: 'jira' | 'fake'; base_url: string | null };
  limits: {
    max_code_files: number;
    max_file_bytes: number;
    max_screenshots: number;
    max_screenshot_bytes: number;
  };
}
