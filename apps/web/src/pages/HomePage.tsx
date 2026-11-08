import { useQuery } from '@tanstack/react-query';
import { Card, CardDescription, CardTitle } from '@/components/ui/card';
import type { HealthResponse } from '@mtj/contracts';
import { apiFetch } from '@/lib/api';

export function HomePage() {
  const health = useQuery({
    queryKey: ['healthz'],
    queryFn: () => apiFetch<HealthResponse>('/healthz'),
  });

  return (
    <Card className="max-w-md">
      <CardTitle>System status</CardTitle>
      <CardDescription>API and database connectivity.</CardDescription>
      <p className="mt-4 text-sm" role="status">
        {health.isPending && 'Checking…'}
        {health.isError && <span className="text-destructive">API unreachable</span>}
        {health.data && (
          <span className="text-success">
            API {health.data.status}, DB {health.data.db}
          </span>
        )}
      </p>
    </Card>
  );
}
