import { Badge, type BadgeProps } from '@/components/ui/badge';
import type { RunStatus } from '@/lib/types';

const STATUS_TONE: Record<RunStatus, BadgeProps['tone']> = {
  queued: 'neutral',
  running: 'info',
  awaiting_review: 'warning',
  creating_tickets: 'info',
  completed: 'success',
  failed: 'danger',
  cancelled: 'neutral',
};

export function StatusBadge({ status }: { status: RunStatus }) {
  return <Badge tone={STATUS_TONE[status]}>{status.replace('_', ' ')}</Badge>;
}
