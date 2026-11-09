import { useEffect, useRef, useState } from 'react';
import type { RunEvent } from './types';

export type StreamState = 'connecting' | 'open' | 'reconnecting' | 'ended';

/**
 * Live progress events for a run over SSE. The browser's EventSource reconnects by itself
 * and sends Last-Event-ID, so the backend only replays newer events. `onEvent` fires for
 * each new event (used to refresh the run detail).
 */
export function useRunEvents(runId: string, onEvent?: (e: RunEvent) => void) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [state, setState] = useState<StreamState>('connecting');
  const [generation, setGeneration] = useState(0);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    const source = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events`);
    const seen = new Set<number>();
    setEvents([]);
    setState('connecting');

    source.onopen = () => setState('open');
    source.onerror = () => {
      if (source.readyState !== EventSource.CLOSED) setState('reconnecting');
    };
    source.addEventListener('progress', (msg) => {
      const event = JSON.parse((msg as MessageEvent<string>).data) as RunEvent;
      if (seen.has(event.id)) return;
      seen.add(event.id);
      setEvents((prev) => [...prev, event]);
      onEventRef.current?.(event);
    });
    source.addEventListener('end', () => {
      source.close();
      setState('ended');
    });
    return () => source.close();
  }, [runId, generation]);

  /** Reopen the stream, e.g. after retrying a failed run. */
  const reconnect = () => setGeneration((g) => g + 1);
  return { events, state, reconnect };
}
