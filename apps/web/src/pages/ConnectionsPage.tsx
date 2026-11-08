import type { ConnectionView, Provider } from '@mtj/contracts';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Card, CardDescription, CardTitle } from '@/components/ui/card';
import { apiFetch } from '@/lib/api';
import { cn } from '@/lib/utils';

const PROVIDER_INFO: Record<Provider, { name: string; purpose: string }> = {
  jira: { name: 'Jira', purpose: 'Create the approved tickets in your project and sprint.' },
  github: { name: 'GitHub', purpose: 'Read-only access to compare requirements with code.' },
  gitlab: { name: 'GitLab', purpose: 'Read-only access to compare requirements with code.' },
  msgraph: { name: 'Microsoft Teams', purpose: 'Fetch meeting transcripts.' },
  spinach: { name: 'Spinach', purpose: 'Fetch meeting transcripts and notes.' },
};

const STATE_LABEL = {
  connected: { text: 'Connected', className: 'bg-success/15 text-success' },
  needs_reauth: { text: 'Reconnect needed', className: 'bg-destructive/15 text-destructive' },
  not_connected: { text: 'Not connected', className: 'bg-muted text-muted-foreground' },
} as const;

export function ConnectionsPage() {
  const queryClient = useQueryClient();
  const connections = useQuery({
    queryKey: ['connections'],
    queryFn: () => apiFetch<ConnectionView[]>('/connections'),
  });
  const disconnect = useMutation({
    mutationFn: (provider: Provider) =>
      apiFetch<void>(`/connections/${provider}`, { method: 'DELETE' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['connections'] }),
  });

  return (
    <section className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Connections</h1>
        <p className="text-sm text-muted-foreground">
          Connect each account once. Tokens are stored encrypted and only used for your runs.
        </p>
      </div>

      {connections.isPending && <p role="status">Loading connections…</p>}
      {connections.isError && (
        <p role="alert" className="text-destructive">
          Could not load connections: {connections.error.message}
        </p>
      )}
      {disconnect.isError && (
        <p role="alert" className="text-destructive">
          Disconnect failed: {disconnect.error.message}
        </p>
      )}

      <ul className="grid gap-4 sm:grid-cols-2">
        {connections.data?.map((c) => {
          const info = PROVIDER_INFO[c.provider];
          const label = STATE_LABEL[c.state];
          return (
            <li key={c.provider}>
              <Card className="flex h-full flex-col gap-3">
                <div className="flex items-start justify-between gap-2">
                  <CardTitle>{info.name}</CardTitle>
                  <span
                    className={cn('rounded-full px-2 py-0.5 text-xs font-medium', label.className)}
                  >
                    {label.text}
                  </span>
                </div>
                <CardDescription>{info.purpose}</CardDescription>
                {c.externalAccountId && (
                  <p className="text-xs text-muted-foreground">Account: {c.externalAccountId}</p>
                )}
                <div className="mt-auto flex gap-2">
                  {c.state === 'not_connected' ? (
                    <Button
                      size="sm"
                      disabled
                      title="OAuth connections arrive in a later milestone"
                    >
                      Connect (coming soon)
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={disconnect.isPending}
                      onClick={() => disconnect.mutate(c.provider)}
                      aria-label={`Disconnect ${info.name}`}
                    >
                      Disconnect
                    </Button>
                  )}
                </div>
              </Card>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
