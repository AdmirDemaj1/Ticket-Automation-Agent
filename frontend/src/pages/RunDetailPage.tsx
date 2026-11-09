import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, ExternalLink } from 'lucide-react';
import { useState, type KeyboardEvent, type ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import { CodeFitPanel } from '@/components/run/CodeFitPanel';
import { DraftEditor } from '@/components/run/DraftEditor';
import { StatusBadge } from '@/components/run/StatusBadge';
import { Badge, type BadgeProps } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardDescription, CardTitle } from '@/components/ui/card';
import { apiFetch } from '@/lib/api';
import { cleanDraft } from '@/lib/drafts';
import { type CodeFinding, type Run, type RunDetail, type TicketDraft } from '@/lib/types';
import { useRunEvents } from '@/lib/useRunEvents';
import { cn } from '@/lib/utils';

export function RunDetailPage() {
  const { runId = '' } = useParams();
  const queryClient = useQueryClient();
  const detail = useQuery({
    queryKey: ['run', runId],
    queryFn: () => apiFetch<RunDetail>(`/runs/${runId}`),
  });
  const stream = useRunEvents(runId, () =>
    queryClient.invalidateQueries({ queryKey: ['run', runId] }),
  );

  const action = useMutation({
    mutationFn: (name: 'cancel' | 'retry' | 'reject') =>
      apiFetch<Run>(`/runs/${runId}/${name}`, { method: 'POST' }),
    onSuccess: async (_, name) => {
      if (name === 'retry') stream.reconnect();
      await queryClient.invalidateQueries({ queryKey: ['run', runId] });
    },
  });

  if (detail.isPending) return <p role="status">Loading run…</p>;
  if (detail.isError)
    return (
      <p role="alert" className="text-destructive">
        Could not load the run: {detail.error.message}
      </p>
    );

  const { run } = detail.data;
  const busy = run.status === 'queued' || run.status === 'running';
  const canCancel = busy || run.status === 'awaiting_review';

  return (
    <section className="max-w-5xl space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">
          {detail.data.transcript_title ?? 'Run'}{' '}
          <span className="text-sm font-normal text-muted-foreground">{run.id.slice(0, 8)}</span>
        </h1>
        <StatusBadge status={run.status} />
        <div className="ml-auto flex gap-2">
          {run.status === 'failed' && (
            <Button size="sm" onClick={() => action.mutate('retry')} disabled={action.isPending}>
              Retry from last step
            </Button>
          )}
          {canCancel && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => action.mutate('cancel')}
              disabled={action.isPending}
            >
              Cancel run
            </Button>
          )}
        </div>
      </div>
      <p className="text-sm text-muted-foreground">
        {run.inputs.repo} @ {run.inputs.branch} → Jira {run.inputs.jira_project_key} ·{' '}
        {detail.data.tokens_used.toLocaleString()} tokens used · started{' '}
        {new Date(run.created_at).toLocaleString()}
      </p>
      {action.isError && (
        <p role="alert" className="text-sm text-destructive">
          {action.error.message}
        </p>
      )}
      {run.error && (
        <Card className="border-destructive/50 p-4" role="alert">
          <p className="text-sm text-destructive">{run.error}</p>
        </Card>
      )}

      <Timeline events={stream.events} state={stream.state} />

      {run.status === 'completed' && <CreatedList detail={detail.data} />}
      {detail.data.review_stage === 'code_fit' && <CodeFitPanel detail={detail.data} />}
      {(detail.data.drafts.length > 0 || detail.data.review_stage === 'code_fit') && (
        <Review
          key={`${run.status}-${detail.data.review_stage}`}
          detail={detail.data}
          onReject={() => action.mutate('reject')}
        />
      )}
    </section>
  );
}

// ---------- timeline ----------

function Timeline({
  events,
  state,
}: {
  events: ReturnType<typeof useRunEvents>['events'];
  state: ReturnType<typeof useRunEvents>['state'];
}) {
  return (
    <Card className="p-4">
      <div className="mb-2 flex items-center gap-2">
        <CardTitle className="text-base">Progress</CardTitle>
        {state === 'reconnecting' && <Badge tone="warning">Reconnecting…</Badge>}
        {state === 'connecting' && <Badge>Connecting…</Badge>}
      </div>
      {events.length === 0 ? (
        <p className="text-sm text-muted-foreground">Waiting for events…</p>
      ) : (
        <ol className="max-h-64 space-y-1 overflow-y-auto text-sm" aria-live="polite">
          {events.map((e) => (
            <li
              key={e.id}
              className={cn(
                'flex gap-3',
                e.level === 'error' && 'text-destructive',
                e.level === 'warning' && 'text-warning',
              )}
            >
              <time className="shrink-0 text-muted-foreground tabular-nums" dateTime={e.ts}>
                {new Date(e.ts).toLocaleTimeString()}
              </time>
              <span>{e.message}</span>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

// ---------- created issues ----------

function CreatedList({ detail }: { detail: RunDetail }) {
  const titles = new Map(detail.drafts.map((d) => [d.draft.temp_id, d.draft.title]));
  if (detail.created.length === 0) return null;
  return (
    <Card className="p-4">
      <CardTitle className="text-base">Jira issues</CardTitle>
      <ul className="mt-2 space-y-1 text-sm">
        {detail.created.map((c) => (
          <li key={c.temp_id} className="flex items-center gap-2">
            <span className="w-8 text-muted-foreground">{c.temp_id}</span>
            {c.url ? (
              <a
                href={c.url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
              >
                {c.key} <ExternalLink aria-hidden className="size-3" />
              </a>
            ) : (
              <Badge tone="danger">failed</Badge>
            )}
            <span>{titles.get(c.temp_id)}</span>
            {c.existed && <Badge>already existed</Badge>}
            {c.error && <span className="text-destructive">{c.error}</span>}
          </li>
        ))}
      </ul>
    </Card>
  );
}

// ---------- review ----------

type Tab = 'summary' | 'code' | 'drafts';
const TABS: { id: Tab; label: string }[] = [
  { id: 'summary', label: 'Summary by screen' },
  { id: 'code', label: 'Code analysis' },
  { id: 'drafts', label: 'Draft tickets' },
];

function Review({ detail, onReject }: { detail: RunDetail; onReject: () => void }) {
  const [tab, setTab] = useState<Tab>(detail.review_stage === 'code_fit' ? 'code' : 'drafts');
  const reviewing = detail.run.status === 'awaiting_review' && detail.review_stage === 'drafts';

  function onKey(e: KeyboardEvent<HTMLDivElement>) {
    const i = TABS.findIndex((t) => t.id === tab);
    if (e.key === 'ArrowRight') setTab(TABS[(i + 1) % TABS.length].id);
    if (e.key === 'ArrowLeft') setTab(TABS[(i + TABS.length - 1) % TABS.length].id);
  }

  return (
    <div className="space-y-3">
      <div
        role="tablist"
        aria-label="Review"
        className="flex gap-1 border-b border-border"
        onKeyDown={onKey}
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls={`panel-${t.id}`}
            tabIndex={tab === t.id ? 0 : -1}
            onClick={() => setTab(t.id)}
            className={cn(
              '-mb-px border-b-2 px-3 py-2 text-sm',
              tab === t.id
                ? 'border-primary font-medium text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground',
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === 'summary' && <SummaryTab detail={detail} />}
        {tab === 'code' && <CodeTab detail={detail} />}
        {tab === 'drafts' &&
          (detail.drafts.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No drafts: the code check stopped the run before drafting.
            </p>
          ) : (
            <DraftsTab detail={detail} reviewing={reviewing} onReject={onReject} />
          ))}
      </div>
    </div>
  );
}

function List({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <h4 className="text-sm font-medium">{title}</h4>
      <ul className="list-disc pl-5 text-sm">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function SummaryTab({ detail }: { detail: RunDetail }) {
  const analysis = detail.meeting_analysis;
  return (
    <div className="space-y-4">
      {detail.screenshots.length > 0 && (
        <div className="flex flex-wrap gap-3">
          {detail.screenshots.map((s) => (
            <figure key={s.order} className="w-48">
              <img
                src={`/api${s.url}`}
                alt={s.caption ?? `Screenshot ${s.order}`}
                className="rounded border border-border"
              />
              <figcaption className="text-xs text-muted-foreground">
                {s.order}. {s.caption ?? 'No caption'}
              </figcaption>
            </figure>
          ))}
        </div>
      )}
      {!analysis ? (
        <p className="text-sm text-muted-foreground">No summary yet.</p>
      ) : (
        <>
          {analysis.screens.map((s) => (
            <Card key={s.screen} className="space-y-2 p-4">
              <CardTitle className="text-base">{s.screen}</CardTitle>
              <List title="Feedback" items={s.feedback} />
              <List title="Decisions" items={s.decisions} />
              <List title="Actions" items={s.actions} />
              <List title="Open questions" items={s.open_questions} />
            </Card>
          ))}
          <List title="Parked" items={analysis.parked} />
          <List title="Notes for the reviewer" items={analysis.notes} />
        </>
      )}
      <Card className="p-4">
        <CardTitle className="text-base">Requirements</CardTitle>
        <ul className="mt-2 space-y-2 text-sm">
          {detail.requirements.map((r) => (
            <li key={r.id}>
              <span className="font-medium">
                {r.id}. {r.title}
              </span>{' '}
              {r.priority_hint && <Badge tone="info">{r.priority_hint} priority</Badge>}{' '}
              {r.screen ? <Badge>{r.screen}</Badge> : <Badge tone="warning">screen unclear</Badge>}
              <p className="text-muted-foreground">{r.detail}</p>
              {r.source_quote && (
                <blockquote className="border-l-2 pl-2 italic">“{r.source_quote}”</blockquote>
              )}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

const FINDING_TONE: Record<CodeFinding['status'], BadgeProps['tone']> = {
  implemented: 'success',
  partial: 'info',
  missing: 'neutral',
  unclear: 'warning',
};

function CodeTab({ detail }: { detail: RunDetail }) {
  const reqs = new Map(detail.requirements.map((r) => [r.id, r]));
  return (
    <div className="space-y-3">
      <CardDescription>
        Files read ({detail.files_read.length}):{' '}
        {detail.files_read.map((f, i) => (
          <span key={f}>
            {i > 0 && ', '}
            <code>{f}</code>
          </span>
        ))}
        . Code analysis by an LLM can miss things; check the evidence.
      </CardDescription>
      {detail.code_findings.map((f) => {
        const warn = f.status === 'unclear' || f.confidence === 'low';
        return (
          <Card key={f.requirement_id} className={cn('space-y-2 p-4', warn && 'border-warning/60')}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">
                {f.requirement_id}. {reqs.get(f.requirement_id)?.title}
              </span>
              <Badge tone={FINDING_TONE[f.status]}>{f.status}</Badge>
              <Badge tone={f.confidence === 'low' ? 'warning' : 'neutral'}>
                {f.confidence} confidence
              </Badge>
              {warn && (
                <span className="inline-flex items-center gap-1 text-xs text-warning">
                  <AlertTriangle aria-hidden className="size-3" /> Check by hand
                </span>
              )}
            </div>
            {f.evidence.length === 0 ? (
              <p className="text-sm text-muted-foreground">No evidence in the files read.</p>
            ) : (
              <ul className="space-y-1 text-sm">
                {f.evidence.map((e, i) => (
                  <li key={i}>
                    <code className="text-xs">
                      {e.path}
                      {e.start_line != null &&
                        `:${e.start_line}${e.end_line != null && e.end_line !== e.start_line ? `-${e.end_line}` : ''}`}
                    </code>{' '}
                    {e.note}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        );
      })}
    </div>
  );
}

function DraftsTab({
  detail,
  reviewing,
  onReject,
}: {
  detail: RunDetail;
  reviewing: boolean;
  onReject: () => void;
}) {
  const queryClient = useQueryClient();
  const runId = detail.run.id;
  const [edits, setEdits] = useState<Record<string, TicketDraft>>({});
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(detail.drafts.filter((d) => d.draft.selected).map((d) => d.draft.temp_id)),
  );
  const [confirming, setConfirming] = useState(false);
  const dirtyIds = Object.keys(edits);
  const issueTypes = detail.run.inputs.issue_types;

  const save = useMutation({
    mutationFn: () =>
      apiFetch(`/runs/${runId}/drafts`, {
        method: 'PUT',
        body: JSON.stringify({
          drafts: Object.values(edits).map((d) => ({
            ...cleanDraft(d),
            selected: selected.has(d.temp_id),
          })),
        }),
      }),
    onSuccess: async () => {
      setEdits({});
      await queryClient.invalidateQueries({ queryKey: ['run', runId] });
    },
  });

  const approve = useMutation({
    mutationFn: () =>
      apiFetch<Run>(`/runs/${runId}/approve`, {
        method: 'POST',
        body: JSON.stringify({ selected: [...selected] }),
      }),
    onSuccess: async () => {
      setConfirming(false);
      await queryClient.invalidateQueries({ queryKey: ['run', runId] });
    },
  });

  const invalid = Object.values(edits).some((d) => !d.title.trim());
  const count = selected.size;

  return (
    <div className="space-y-3">
      {reviewing && (
        <Card className="sticky top-0 z-10 flex flex-wrap items-center gap-3 p-3">
          <span className="text-sm">
            {count} of {detail.drafts.length} tickets selected
          </span>
          <div className="ml-auto flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={dirtyIds.length === 0 || invalid || save.isPending}
              onClick={() => save.mutate()}
            >
              {save.isPending
                ? 'Saving…'
                : `Save edits${dirtyIds.length ? ` (${dirtyIds.length})` : ''}`}
            </Button>
            <Button variant="outline" size="sm" onClick={onReject} disabled={approve.isPending}>
              Reject
            </Button>
            <Button
              size="sm"
              disabled={dirtyIds.length > 0 || count === 0 || approve.isPending}
              title={dirtyIds.length > 0 ? 'Save your edits first' : undefined}
              onClick={() => setConfirming(true)}
            >
              Approve &amp; create in Jira
            </Button>
          </div>
          {dirtyIds.length > 0 && (
            <p className="w-full text-xs text-warning">Save your edits before approving.</p>
          )}
          {invalid && (
            <p className="w-full text-xs text-destructive">Every ticket needs a title.</p>
          )}
          {save.isError && (
            <p role="alert" className="w-full text-sm text-destructive">
              Could not save: {save.error.message}
            </p>
          )}
        </Card>
      )}

      {confirming && (
        <ConfirmDialog
          title="Create Jira issues?"
          onCancel={() => setConfirming(false)}
          onConfirm={() => approve.mutate()}
          pending={approve.isPending}
          error={approve.error?.message}
        >
          <p>
            This creates <strong>{count}</strong> issue{count === 1 ? '' : 's'} in Jira project{' '}
            <strong>{detail.run.inputs.jira_project_key}</strong>.
          </p>
          <p className="text-muted-foreground">
            Each issue gets the labels <code>{detail.jira_labels[0]}</code> and{' '}
            <code>{detail.jira_labels[1]}</code>, so approving again never creates duplicates.
          </p>
        </ConfirmDialog>
      )}

      {detail.drafts.map(({ draft, jira_key }) => {
        const current = edits[draft.temp_id] ?? draft;
        return (
          <div key={draft.temp_id}>
            {jira_key && <p className="mb-1 text-xs text-success">Created as {jira_key}</p>}
            <DraftEditor
              draft={current}
              selected={selected.has(draft.temp_id)}
              onSelect={(on) =>
                setSelected((prev) => {
                  const next = new Set(prev);
                  if (on) next.add(draft.temp_id);
                  else next.delete(draft.temp_id);
                  return next;
                })
              }
              onChange={(d) => setEdits((prev) => ({ ...prev, [d.temp_id]: d }))}
              findings={detail.code_findings}
              issueTypes={issueTypes}
              readOnly={!reviewing}
              dirty={draft.temp_id in edits}
            />
          </div>
        );
      })}
      {!reviewing && (
        <p className="text-sm text-muted-foreground">
          Review is closed for this run. <Link to="/runs/new">Start a new run</Link>.
        </p>
      )}
    </div>
  );
}

function ConfirmDialog({
  title,
  children,
  onCancel,
  onConfirm,
  pending,
  error,
}: {
  title: string;
  children: ReactNode;
  onCancel: () => void;
  onConfirm: () => void;
  pending: boolean;
  error?: string;
}) {
  return (
    <div
      className="fixed inset-0 z-20 flex items-center justify-center bg-black/40 p-4"
      onKeyDown={(e) => e.key === 'Escape' && onCancel()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        className="w-full max-w-md space-y-3 rounded-[var(--radius)] bg-background p-6 text-sm shadow-lg"
      >
        <h2 id="confirm-title" className="text-lg font-semibold">
          {title}
        </h2>
        {children}
        {error && (
          <p role="alert" className="text-destructive">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onCancel} autoFocus>
            Cancel
          </Button>
          <Button onClick={onConfirm} disabled={pending}>
            {pending ? 'Creating…' : 'Create issues'}
          </Button>
        </div>
      </div>
    </div>
  );
}
