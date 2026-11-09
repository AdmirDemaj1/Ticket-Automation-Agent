import { AlertTriangle } from 'lucide-react';
import { useId } from 'react';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { draftWarnings } from '@/lib/drafts';
import type { CodeFinding, TicketDraft, TicketType } from '@/lib/types';

const STATUS_LABEL: Record<TicketDraft['status_in_code'], string> = {
  new: 'New',
  extends_existing: 'Extends existing code',
  already_done: 'Looks already done',
};

export function DraftEditor({
  draft,
  selected,
  onSelect,
  onChange,
  findings,
  issueTypes,
  readOnly,
  dirty,
}: {
  draft: TicketDraft;
  selected: boolean;
  onSelect: (selected: boolean) => void;
  onChange: (draft: TicketDraft) => void;
  findings: CodeFinding[];
  issueTypes: TicketType[];
  readOnly: boolean;
  dirty: boolean;
}) {
  const id = useId();
  const warnings = draftWarnings(draft, findings);
  const set = <K extends keyof TicketDraft>(key: K, value: TicketDraft[K]) =>
    onChange({ ...draft, [key]: value });

  return (
    <Card className="space-y-3 p-4" aria-labelledby={`${id}-title`}>
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-sm font-medium">
          <input
            type="checkbox"
            checked={selected}
            disabled={readOnly}
            onChange={(e) => onSelect(e.target.checked)}
          />
          <span id={`${id}-title`}>Include {draft.temp_id}</span>
        </label>
        <Badge tone={draft.status_in_code === 'already_done' ? 'warning' : 'info'}>
          {STATUS_LABEL[draft.status_in_code]}
        </Badge>
        {draft.requirement_ids.map((r) => (
          <Badge key={r}>{r}</Badge>
        ))}
        {dirty && <Badge tone="warning">Unsaved</Badge>}
      </div>

      {warnings.length > 0 && (
        <div className="flex gap-2 rounded-[var(--radius)] bg-warning/10 p-2 text-sm text-warning">
          <AlertTriangle aria-hidden className="mt-0.5 size-4 shrink-0" />
          <ul>
            {warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-[1fr_10rem]">
        <div className="space-y-1">
          <Label htmlFor={`${id}-t`}>Title</Label>
          <Input
            id={`${id}-t`}
            value={draft.title}
            maxLength={200}
            readOnly={readOnly}
            aria-invalid={!draft.title.trim()}
            onChange={(e) => set('title', e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor={`${id}-type`}>Type</Label>
          <select
            id={`${id}-type`}
            value={draft.type}
            disabled={readOnly}
            onChange={(e) => set('type', e.target.value as TicketType)}
            className="flex h-9 w-full rounded-[var(--radius)] border border-border bg-background px-3 text-sm"
          >
            {Array.from(new Set([...issueTypes, draft.type])).map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="space-y-1">
        <Label htmlFor={`${id}-d`}>Description</Label>
        <Textarea
          id={`${id}-d`}
          rows={5}
          value={draft.description}
          readOnly={readOnly}
          onChange={(e) => set('description', e.target.value)}
        />
      </div>

      <div className="space-y-1">
        <Label htmlFor={`${id}-ac`}>Acceptance criteria (one per line)</Label>
        <Textarea
          id={`${id}-ac`}
          rows={Math.max(3, draft.acceptance_criteria.length)}
          value={draft.acceptance_criteria.join('\n')}
          readOnly={readOnly}
          onChange={(e) => set('acceptance_criteria', e.target.value.split('\n'))}
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor={`${id}-l`}>Labels (comma separated)</Label>
          <Input
            id={`${id}-l`}
            value={draft.labels.join(', ')}
            readOnly={readOnly}
            onChange={(e) =>
              set(
                'labels',
                e.target.value.split(',').map((s) => s.trimStart()),
              )
            }
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor={`${id}-e`}>Estimate</Label>
          <Input
            id={`${id}-e`}
            value={draft.estimate ?? ''}
            readOnly={readOnly}
            placeholder="e.g. 3d"
            onChange={(e) => set('estimate', e.target.value || null)}
          />
        </div>
      </div>

      {draft.related_files.length > 0 && (
        <p className="text-xs text-muted-foreground">
          Related files:{' '}
          {draft.related_files.map((f, i) => (
            <span key={f}>
              {i > 0 && ', '}
              <code>{f}</code>
            </span>
          ))}
        </p>
      )}
    </Card>
  );
}
