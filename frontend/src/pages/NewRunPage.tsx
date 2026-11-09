import { useMutation, useQuery } from '@tanstack/react-query';
import { ArrowDown, ArrowUp, GripVertical, X } from 'lucide-react';
import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardDescription, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { apiFetch } from '@/lib/api';
import type {
  ConfigStatus,
  Estimate,
  JiraIssueType,
  JiraProject,
  Repo,
  TicketType,
} from '@/lib/types';
import { cn } from '@/lib/utils';

const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp'];
const TRANSCRIPT_ACCEPT = '.vtt,.txt,.docx';
const DEFAULT_TYPES: TicketType[] = ['Story', 'Task', 'Bug'];

interface Shot {
  id: string;
  file: File;
  caption: string;
  preview: string;
}

let shotCounter = 0;

export function NewRunPage() {
  const navigate = useNavigate();
  const ids = useId();

  // ---- transcript ----
  const [mode, setMode] = useState<'upload' | 'paste'>('upload');
  const [transcriptFile, setTranscriptFile] = useState<File | null>(null);
  const [transcriptText, setTranscriptText] = useState('');

  // ---- screenshots ----
  const [shots, setShots] = useState<Shot[]>([]);
  const [shotError, setShotError] = useState<string | null>(null);
  const dragIndex = useRef<number | null>(null);
  const shotsRef = useRef(shots);
  shotsRef.current = shots;
  useEffect(() => () => shotsRef.current.forEach((s) => URL.revokeObjectURL(s.preview)), []);

  // ---- targets ----
  const [repo, setRepo] = useState('');
  const [branch, setBranch] = useState('');
  const [project, setProject] = useState('');
  const [issueTypes, setIssueTypes] = useState<TicketType[] | null>(null);
  const [consent, setConsent] = useState(false);
  const [formErrors, setFormErrors] = useState<string[]>([]);

  const config = useQuery({
    queryKey: ['config-status'],
    queryFn: () => apiFetch<ConfigStatus>('/config/status'),
  });
  const repos = useQuery({ queryKey: ['repos'], queryFn: () => apiFetch<Repo[]>('/code/repos') });
  const selectedRepo = repo || repos.data?.[0]?.id || '';
  const branches = useQuery({
    queryKey: ['branches', selectedRepo],
    queryFn: () => apiFetch<string[]>(`/code/repos/${selectedRepo}/branches`),
    enabled: Boolean(selectedRepo),
  });
  const defaultBranch = repos.data?.find((r) => r.id === selectedRepo)?.default_branch;
  const selectedBranch =
    branch && branches.data?.includes(branch)
      ? branch
      : (branches.data?.find((b) => b === defaultBranch) ?? branches.data?.[0] ?? '');

  const projects = useQuery({
    queryKey: ['jira-projects'],
    queryFn: () => apiFetch<JiraProject[]>('/jira/projects'),
  });
  const selectedProject = project || projects.data?.[0]?.key || '';
  const types = useQuery({
    queryKey: ['issue-types', selectedProject],
    queryFn: () =>
      apiFetch<JiraIssueType[]>(
        `/jira/projects/${encodeURIComponent(selectedProject)}/issue-types`,
      ),
    enabled: Boolean(selectedProject),
  });
  const availableTypes = (types.data ?? [])
    .map((t) => t.name)
    .filter((n): n is TicketType => ['Story', 'Task', 'Bug', 'Sub-task'].includes(n));
  const chosenTypes =
    issueTypes?.filter((t) => availableTypes.includes(t)) ??
    DEFAULT_TYPES.filter((t) => availableTypes.includes(t));

  // ---- estimate ----
  const transcriptChars = mode === 'upload' ? (transcriptFile?.size ?? 0) : transcriptText.length;
  const estimate = useQuery({
    queryKey: ['estimate', transcriptChars, shots.length],
    queryFn: () =>
      apiFetch<Estimate>(
        `/runs/estimate?transcript_chars=${transcriptChars}&screenshots=${shots.length}`,
      ),
    enabled: transcriptChars > 0,
  });

  const maxShots = config.data?.limits.max_screenshots ?? 10;
  const maxShotBytes = config.data?.limits.max_screenshot_bytes ?? 8_000_000;

  function addShots(files: FileList | null) {
    if (!files) return;
    const added: Shot[] = [];
    const problems: string[] = [];
    for (const file of Array.from(files)) {
      if (!IMAGE_TYPES.includes(file.type)) problems.push(`${file.name}: not PNG, JPEG or WebP`);
      else if (file.size > maxShotBytes)
        problems.push(`${file.name}: larger than ${Math.round(maxShotBytes / 1e6)} MB`);
      else
        added.push({
          id: `shot-${++shotCounter}`,
          file,
          caption: file.name.replace(/\.[^.]+$/, '').replace(/^\d+[-_ ]*/, ''),
          preview: URL.createObjectURL(file),
        });
    }
    const room = maxShots - shots.length;
    if (added.length > room) {
      problems.push(`At most ${maxShots} screenshots; ${added.length - room} not added`);
      added.splice(room).forEach((s) => URL.revokeObjectURL(s.preview));
    }
    setShots((prev) => [...prev, ...added]);
    setShotError(problems.length ? problems.join('. ') : null);
  }

  function moveShot(from: number, to: number) {
    if (to < 0 || to >= shots.length || from === to) return;
    setShots((prev) => {
      const next = [...prev];
      const [item] = next.splice(from, 1);
      next.splice(to, 0, item);
      return next;
    });
  }

  function removeShot(id: string) {
    setShots((prev) => {
      const gone = prev.find((s) => s.id === id);
      if (gone) URL.revokeObjectURL(gone.preview);
      return prev.filter((s) => s.id !== id);
    });
  }

  const submit = useMutation({
    mutationFn: (body: FormData) => apiFetch<{ run_id: string }>('/runs', { method: 'POST', body }),
    onSuccess: ({ run_id }) => navigate(`/runs/${run_id}`),
  });

  const transcriptReady =
    mode === 'upload' ? Boolean(transcriptFile) : Boolean(transcriptText.trim());

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const errors: string[] = [];
    if (!transcriptReady) errors.push('Add a transcript file or paste the transcript text.');
    if (!selectedRepo || !selectedBranch) errors.push('Choose a repository and branch.');
    if (!selectedProject) errors.push('Choose a Jira project.');
    if (chosenTypes.length === 0) errors.push('Choose at least one issue type.');
    if (!consent) errors.push('Confirm that the data may be sent to the Claude API.');
    setFormErrors(errors);
    if (errors.length) return;

    const body = new FormData();
    body.set(
      'inputs',
      JSON.stringify({
        repo: selectedRepo,
        branch: selectedBranch,
        jira_project_key: selectedProject,
        issue_types: chosenTypes,
        sprint_id: null,
      }),
    );
    if (mode === 'upload' && transcriptFile) body.set('transcript_file', transcriptFile);
    else body.set('transcript_text', transcriptText);
    shots.forEach((s) => body.append('screenshots', s.file));
    body.set('captions', JSON.stringify(shots.map((s) => s.caption.trim() || null)));
    submit.mutate(body);
  }

  const budget = config.data?.llm.max_tokens_per_run;
  const overBudget = Boolean(
    estimate.data && estimate.data.tokens > estimate.data.max_tokens_per_run,
  );

  return (
    <form onSubmit={onSubmit} className="max-w-3xl space-y-6" noValidate>
      <h1 className="text-xl font-semibold">New run</h1>

      {/* 1. Transcript */}
      <Card>
        <fieldset className="space-y-3">
          <legend className="text-lg font-semibold">1. Meeting transcript</legend>
          <div role="radiogroup" aria-label="Transcript source" className="flex gap-4 text-sm">
            {(['upload', 'paste'] as const).map((m) => (
              <label key={m} className="flex items-center gap-2">
                <input
                  type="radio"
                  name="transcript-mode"
                  checked={mode === m}
                  onChange={() => setMode(m)}
                />
                {m === 'upload' ? 'Upload a file' : 'Paste text'}
              </label>
            ))}
          </div>
          {mode === 'upload' ? (
            <div className="space-y-1">
              <Label htmlFor={`${ids}-transcript`}>Transcript file (.vtt, .txt or .docx)</Label>
              <Input
                id={`${ids}-transcript`}
                type="file"
                accept={TRANSCRIPT_ACCEPT}
                onChange={(e) => setTranscriptFile(e.target.files?.[0] ?? null)}
              />
            </div>
          ) : (
            <div className="space-y-1">
              <Label htmlFor={`${ids}-text`}>Transcript text</Label>
              <Textarea
                id={`${ids}-text`}
                rows={8}
                value={transcriptText}
                onChange={(e) => setTranscriptText(e.target.value)}
                placeholder="Anna: Let's look at the login screen…"
              />
            </div>
          )}
        </fieldset>
      </Card>

      {/* 2. Screenshots */}
      <Card>
        <fieldset className="space-y-3">
          <legend className="text-lg font-semibold">2. Screenshots (optional)</legend>
          <CardDescription>
            PNG, JPEG or WebP, up to {maxShots}. They are sent in this order; drag or use the arrows
            to reorder. Metadata such as EXIF is removed on upload.
          </CardDescription>
          <Label htmlFor={`${ids}-shots`} className="sr-only">
            Add screenshots
          </Label>
          <Input
            id={`${ids}-shots`}
            type="file"
            accept={IMAGE_TYPES.join(',')}
            multiple
            onChange={(e) => {
              addShots(e.target.files);
              e.target.value = '';
            }}
          />
          {shotError && (
            <p role="alert" className="text-sm text-destructive">
              {shotError}
            </p>
          )}
          {shots.length > 0 && (
            <ol className="space-y-2" aria-label="Screenshots in order">
              {shots.map((shot, index) => (
                <li
                  key={shot.id}
                  draggable
                  onDragStart={() => (dragIndex.current = index)}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={() => {
                    if (dragIndex.current !== null) moveShot(dragIndex.current, index);
                    dragIndex.current = null;
                  }}
                  className="flex items-center gap-3 rounded-[var(--radius)] border border-border p-2"
                >
                  <GripVertical aria-hidden className="size-4 cursor-grab text-muted-foreground" />
                  <span className="w-5 text-sm text-muted-foreground">{index + 1}</span>
                  <img src={shot.preview} alt="" className="h-12 w-20 rounded object-cover" />
                  <div className="flex-1 space-y-1">
                    <Label htmlFor={`${shot.id}-caption`} className="text-xs">
                      Caption for {shot.file.name}
                    </Label>
                    <Input
                      id={`${shot.id}-caption`}
                      value={shot.caption}
                      maxLength={300}
                      onChange={(e) =>
                        setShots((prev) =>
                          prev.map((s) =>
                            s.id === shot.id ? { ...s, caption: e.target.value } : s,
                          ),
                        )
                      }
                    />
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={`Move ${shot.file.name} up`}
                    disabled={index === 0}
                    onClick={() => moveShot(index, index - 1)}
                  >
                    <ArrowUp className="size-4" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={`Move ${shot.file.name} down`}
                    disabled={index === shots.length - 1}
                    onClick={() => moveShot(index, index + 1)}
                  >
                    <ArrowDown className="size-4" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={`Remove ${shot.file.name}`}
                    onClick={() => removeShot(shot.id)}
                  >
                    <X className="size-4" />
                  </Button>
                </li>
              ))}
            </ol>
          )}
        </fieldset>
      </Card>

      {/* 3. Targets */}
      <Card>
        <fieldset className="grid gap-4 sm:grid-cols-2">
          <legend className="mb-3 text-lg font-semibold">3. Repository and Jira</legend>
          <Picker
            id={`${ids}-repo`}
            label="Repository"
            value={selectedRepo}
            onChange={(v) => {
              setRepo(v);
              setBranch('');
            }}
            options={(repos.data ?? []).map((r) => ({ value: r.id, label: r.name }))}
            loading={repos.isPending}
            error={repos.error?.message}
          />
          <Picker
            id={`${ids}-branch`}
            label="Branch"
            value={selectedBranch}
            onChange={setBranch}
            options={(branches.data ?? []).map((b) => ({ value: b, label: b }))}
            loading={branches.isPending && Boolean(selectedRepo)}
            error={branches.error?.message}
          />
          <Picker
            id={`${ids}-project`}
            label="Jira project"
            value={selectedProject}
            onChange={(v) => {
              setProject(v);
              setIssueTypes(null);
            }}
            options={(projects.data ?? []).map((p) => ({
              value: p.key,
              label: `${p.name} (${p.key})`,
            }))}
            loading={projects.isPending}
            error={projects.error?.message}
          />
          <fieldset className="space-y-1">
            <legend className="text-sm font-medium">Issue types the drafts may use</legend>
            {types.isError && <p className="text-sm text-destructive">{types.error.message}</p>}
            <div className="flex flex-wrap gap-3 pt-1">
              {availableTypes.map((t) => (
                <label key={t} className="flex items-center gap-1.5 text-sm">
                  <input
                    type="checkbox"
                    checked={chosenTypes.includes(t)}
                    onChange={(e) =>
                      setIssueTypes(
                        e.target.checked ? [...chosenTypes, t] : chosenTypes.filter((x) => x !== t),
                      )
                    }
                  />
                  {t}
                </label>
              ))}
            </div>
          </fieldset>
          <p className="text-xs text-muted-foreground sm:col-span-2">
            Sprint assignment arrives with real Jira (milestone M4); tickets go to the backlog.
          </p>
        </fieldset>
      </Card>

      {/* Start */}
      <Card className="space-y-3">
        <CardTitle>Start</CardTitle>
        <p className="text-sm" aria-live="polite">
          {estimate.data ? (
            <>
              Estimated Claude usage: about{' '}
              <strong>{estimate.data.tokens.toLocaleString()} tokens</strong>
              {budget ? ` (budget ${budget.toLocaleString()} per run)` : ''}.
              {overBudget && (
                <span className="text-destructive"> This is over the per-run budget.</span>
              )}
            </>
          ) : (
            <span className="text-muted-foreground">
              Add a transcript to see the estimated token use.
            </span>
          )}
        </p>
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-1"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
          />
          <span>
            Transcript, screenshots and code excerpts are sent to the Claude API. I am allowed to
            share them, and meeting participants know a transcript was used.
          </span>
        </label>
        {formErrors.length > 0 && (
          <ul role="alert" className="list-disc pl-5 text-sm text-destructive">
            {formErrors.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        )}
        {submit.isError && (
          <p role="alert" className="text-sm text-destructive">
            Could not start the run: {submit.error.message}
          </p>
        )}
        <Button type="submit" disabled={submit.isPending}>
          {submit.isPending ? 'Starting…' : 'Start'}
        </Button>
      </Card>
    </form>
  );
}

function Picker({
  id,
  label,
  value,
  onChange,
  options,
  loading,
  error,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  loading: boolean;
  error?: string;
}) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{label}</Label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={loading || options.length === 0}
        aria-invalid={Boolean(error)}
        className={cn(
          'flex h-9 w-full rounded-[var(--radius)] border border-border bg-background px-3 text-sm focus-visible:outline-2 focus-visible:outline-primary disabled:opacity-50',
          error && 'border-destructive',
        )}
      >
        {loading && <option>Loading…</option>}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
