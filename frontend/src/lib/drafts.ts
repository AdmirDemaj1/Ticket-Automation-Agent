import type { CodeFinding, TicketDraft } from './types';

/** Why a draft deserves a second look, from the findings of its requirements. */
export function draftWarnings(draft: TicketDraft, findings: CodeFinding[]): string[] {
  const linked = findings.filter((f) => draft.requirement_ids.includes(f.requirement_id));
  const out: string[] = [];
  if (linked.some((f) => f.status === 'unclear'))
    out.push('The code could not confirm the state of this work.');
  if (linked.some((f) => f.confidence === 'low')) out.push('Low-confidence code analysis.');
  if (draft.status_in_code === 'already_done')
    out.push('The analysis says this may already be implemented.');
  return out;
}

/** Trim the free-text list fields before saving. */
export function cleanDraft(draft: TicketDraft): TicketDraft {
  return {
    ...draft,
    title: draft.title.trim(),
    acceptance_criteria: draft.acceptance_criteria.map((c) => c.trim()).filter(Boolean),
    labels: draft.labels.map((l) => l.trim()).filter(Boolean),
    estimate: draft.estimate?.trim() || null,
  };
}
