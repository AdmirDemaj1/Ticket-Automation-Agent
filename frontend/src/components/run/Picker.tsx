import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';

/** A labelled native select with loading and error states. */
export function Picker({
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
