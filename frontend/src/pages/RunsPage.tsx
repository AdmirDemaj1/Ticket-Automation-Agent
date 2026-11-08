import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { apiFetch } from '@/lib/api';
import type { Run } from '@/lib/types';

export function RunsPage() {
  const runs = useQuery({ queryKey: ['runs'], queryFn: () => apiFetch<Run[]>('/runs') });

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Runs</h1>
        <Button asChild>
          <Link to="/runs/new">New run</Link>
        </Button>
      </div>

      {runs.isPending && <p role="status">Loading runs…</p>}
      {runs.isError && (
        <p role="alert" className="text-destructive">
          Could not load runs: {runs.error.message}
        </p>
      )}
      {runs.data?.length === 0 && (
        <Card>
          <p className="text-sm text-muted-foreground">
            No runs yet. Start one from a meeting transcript.
          </p>
        </Card>
      )}
      {runs.data && runs.data.length > 0 && (
        <table className="w-full text-left text-sm">
          <thead className="text-muted-foreground">
            <tr>
              <th className="py-2 font-medium">Created</th>
              <th className="py-2 font-medium">Repository</th>
              <th className="py-2 font-medium">Jira project</th>
              <th className="py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {runs.data.map((run) => (
              <tr key={run.id} className="border-t border-border">
                <td className="py-2">{new Date(run.created_at).toLocaleString()}</td>
                <td className="py-2">
                  {run.inputs.repo} @ {run.inputs.branch}
                </td>
                <td className="py-2">{run.inputs.jira_project_key}</td>
                <td className="py-2">{run.status.replace('_', ' ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
