/** Response shapes from the FastAPI backend (mirrors backend/app/models.py and routes). */

export type RunStatus =
  | 'queued'
  | 'running'
  | 'awaiting_review'
  | 'creating_tickets'
  | 'completed'
  | 'failed'
  | 'cancelled';

export interface RunInputs {
  repo: string;
  branch: string;
  jira_project_key: string;
  issue_types: string[];
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

export interface ConfigStatus {
  llm: { model: string; api_key_set: boolean; max_tokens_per_run: number };
  code: { provider: 'github' | 'gitlab' | 'fake'; base_url: string | null };
  jira: { provider: 'jira' | 'fake'; base_url: string | null };
  limits: {
    max_code_files: number;
    max_file_bytes: number;
    max_screenshots: number;
    max_screenshot_bytes: number;
  };
}
