import { useQuery } from '@tanstack/react-query';
import { Card, CardDescription, CardTitle } from '@/components/ui/card';
import { apiFetch } from '@/lib/api';
import type { ConfigStatus } from '@/lib/types';
import { cn } from '@/lib/utils';

function Badge({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <span
      className={cn(
        'rounded-full px-2 py-0.5 text-xs font-medium',
        ok ? 'bg-success/15 text-success' : 'bg-muted text-muted-foreground',
      )}
    >
      {children}
    </span>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

export function StatusPage() {
  const health = useQuery({
    queryKey: ['healthz'],
    queryFn: () => apiFetch<{ status: string }>('/healthz'),
  });
  const config = useQuery({
    queryKey: ['config-status'],
    queryFn: () => apiFetch<ConfigStatus>('/config/status'),
  });

  return (
    <section className="max-w-xl space-y-4">
      <h1 className="text-xl font-semibold">Setup status</h1>
      <Card>
        <CardTitle>Backend</CardTitle>
        <p className="mt-2 text-sm" role="status">
          {health.isPending && 'Checking…'}
          {health.isError && <span className="text-destructive">Backend unreachable</span>}
          {health.data && <span className="text-success">Backend running</span>}
        </p>
      </Card>

      <Card>
        <CardTitle>Providers</CardTitle>
        <CardDescription>
          Configured in the repo-root .env file. Secrets are never shown.
        </CardDescription>
        {config.isPending && <p className="mt-2 text-sm">Loading…</p>}
        {config.isError && (
          <p role="alert" className="mt-2 text-sm text-destructive">
            Could not load configuration: {config.error.message}
          </p>
        )}
        {config.data && (
          <dl className="mt-2 divide-y divide-border">
            <Row
              label="Claude API"
              value={
                <span className="flex items-center gap-2">
                  <code className="text-xs">{config.data.llm.model}</code>
                  {config.data.llm.provider === 'fake' && (
                    <Badge ok={false}>fake: recorded responses</Badge>
                  )}
                  <Badge ok={config.data.llm.api_key_set}>
                    {config.data.llm.api_key_set ? 'API key set' : 'No API key'}
                  </Badge>
                </span>
              }
            />
            <Row
              label="Code"
              value={
                <Badge ok={config.data.code.provider !== 'fake'}>{config.data.code.provider}</Badge>
              }
            />
            <Row
              label="Jira"
              value={
                <Badge ok={config.data.jira.provider !== 'fake'}>{config.data.jira.provider}</Badge>
              }
            />
          </dl>
        )}
      </Card>
    </section>
  );
}
