import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle } from 'lucide-react';
import { useId, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Picker } from '@/components/run/Picker';
import { Button } from '@/components/ui/button';
import { Card, CardTitle } from '@/components/ui/card';
import { apiFetch } from '@/lib/api';
import type { Repo, Run, RunDetail } from '@/lib/types';

const VERDICT: Record<string, string> = {
  does_not_match: 'This repository does not seem to be the code this meeting is about.',
  cannot_tell: 'Too little of the code could be checked to trust the analysis.',
  partly: 'Only a small part of the meeting could be checked against this code.',
  matches: 'Most requirements could not be checked against the code that was read.',
};

/** Shown instead of drafts when the code-fit check stopped the run. */
export function CodeFitPanel({ detail }: { detail: RunDetail }) {
  const fit = detail.code_fit;
  const runId = detail.run.id;
  const ids = useId();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [repo, setRepo] = useState('');
  const [branch, setBranch] = useState('');

  const repos = useQuery({ queryKey: ['repos'], queryFn: () => apiFetch<Repo[]>('/code/repos') });
  const others = (repos.data ?? []).filter((r) => r.id !== detail.run.inputs.repo);
  const selectedRepo = repo || others[0]?.id || '';
  const branches = useQuery({
    queryKey: ['branches', selectedRepo],
    queryFn: () => apiFetch<string[]>(`/code/repos/${selectedRepo}/branches`),
    enabled: Boolean(selectedRepo),
  });
  const defaultBranch = others.find((r) => r.id === selectedRepo)?.default_branch;
  const selectedBranch =
    branch && branches.data?.includes(branch)
      ? branch
      : (branches.data?.find((b) => b === defaultBranch) ?? branches.data?.[0] ?? '');

  const rerun = useMutation({
    mutationFn: () =>
      apiFetch<{ run_id: string }>(`/runs/${runId}/rerun`, {
        method: 'POST',
        body: JSON.stringify({ repo: selectedRepo, branch: selectedBranch }),
      }),
    onSuccess: ({ run_id }) => navigate(`/runs/${run_id}`),
  });
  const decide = useMutation({
    mutationFn: (decision: 'draft_anyway' | 'stop') =>
      apiFetch<Run>(`/runs/${runId}/code-fit`, {
        method: 'POST',
        body: JSON.stringify({ decision }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['run', runId] }),
  });
  const busy = rerun.isPending || decide.isPending;

  return (
    <Card className="space-y-4 border-warning/60 p-4" role="region" aria-label="Code check">
      <div className="flex gap-3">
        <AlertTriangle aria-hidden className="mt-0.5 size-5 shrink-0 text-warning" />
        <div className="space-y-1">
          <CardTitle className="text-base">No tickets were drafted</CardTitle>
          <p className="text-sm">{VERDICT[fit?.verdict ?? 'cannot_tell']}</p>
          {fit?.reason && <p className="text-sm text-muted-foreground">{fit.reason}</p>}
          {fit && (
            <p className="text-sm text-muted-foreground">
              {fit.confident} of {fit.total} requirements could be checked with confidence, in{' '}
              {fit.files_read} file{fit.files_read === 1 ? '' : 's'} read from{' '}
              <code>
                {detail.run.inputs.repo} @ {detail.run.inputs.branch}
              </code>
              . See the <em>Code analysis</em> tab for details.
            </p>
          )}
        </div>
      </div>

      <div className="space-y-2 rounded-[var(--radius)] bg-muted p-3">
        <p className="text-sm font-medium">Try another repository or branch</p>
        <p className="text-xs text-muted-foreground">
          Reuses this meeting's transcript, screenshots and requirements, so only the code is
          checked again.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Picker
            id={`${ids}-repo`}
            label="Repository"
            value={selectedRepo}
            onChange={(v) => {
              setRepo(v);
              setBranch('');
            }}
            options={others.map((r) => ({ value: r.id, label: r.name }))}
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
        </div>
        {repos.data && others.length === 0 && (
          <p className="text-xs text-muted-foreground">
            The token can read no other repository. Add one to the token's repository selection,
            then reload.
          </p>
        )}
        <Button
          size="sm"
          onClick={() => rerun.mutate()}
          disabled={!selectedRepo || !selectedBranch || busy}
        >
          {rerun.isPending ? 'Starting…' : 'Re-run with this repository'}
        </Button>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => decide.mutate('draft_anyway')}
          disabled={busy}
        >
          Draft tickets anyway
        </Button>
        <Button variant="ghost" size="sm" onClick={() => decide.mutate('stop')} disabled={busy}>
          Stop
        </Button>
      </div>
      {(rerun.isError || decide.isError) && (
        <p role="alert" className="text-sm text-destructive">
          {(rerun.error ?? decide.error)?.message}
        </p>
      )}
    </Card>
  );
}
