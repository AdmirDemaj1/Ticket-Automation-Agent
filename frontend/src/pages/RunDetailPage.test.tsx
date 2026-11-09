import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { RunDetail, TicketDraft } from '@/lib/types';
import { stubEventSource, type FakeEventSource } from '@/test/event-source';
import { json, mockFetch } from '@/test/fetch-mock';
import { renderWithProviders } from '@/test/render';
import { RunDetailPage } from './RunDetailPage';

let sources: typeof FakeEventSource;
beforeEach(() => {
  sources = stubEventSource();
});
afterEach(() => vi.unstubAllGlobals());

function draft(temp_id: string, extra: Partial<TicketDraft> = {}): TicketDraft {
  return {
    temp_id,
    type: 'Story',
    title: `Ticket ${temp_id}`,
    description: 'Build it.',
    acceptance_criteria: ['It works'],
    estimate: null,
    labels: ['login'],
    related_files: ['src/pages/Login.tsx'],
    requirement_ids: [temp_id.replace('T', 'R')],
    status_in_code: 'new',
    selected: true,
    ...extra,
  };
}

function detail(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    run: {
      id: 'r1',
      status: 'awaiting_review',
      inputs: {
        repo: 'fixtures/demo-app',
        branch: 'main',
        jira_project_key: 'DEMO',
        issue_types: ['Story', 'Task'],
        sprint_id: null,
      },
      error: null,
      created_at: '2026-11-09T10:00:00.000+00:00',
      updated_at: '2026-11-09T10:01:00.000+00:00',
    },
    transcript_title: 'Design review',
    screenshots: [{ order: 1, caption: 'Login', url: '/runs/r1/screenshots/1' }],
    meeting_analysis: {
      screens: [
        {
          screen: 'Login',
          feedback: ['Users ask how to reset passwords.'],
          decisions: ['Add a reset link.'],
          actions: [],
          open_questions: ['Does the toggle exist?'],
        },
      ],
      parked: ['Dark mode'],
      notes: [],
    },
    requirements: [
      {
        id: 'R1',
        title: 'Forgot password link',
        detail: 'Under the field.',
        screen: 'Login',
        source_quote: 'We need a link',
        priority_hint: 'high',
      },
      {
        id: 'R2',
        title: 'Inline errors',
        detail: 'Red text.',
        screen: null,
        source_quote: null,
        priority_hint: null,
      },
    ],
    code_findings: [
      {
        requirement_id: 'R1',
        status: 'missing',
        evidence: [
          { path: 'src/pages/Login.tsx', start_line: 28, end_line: 35, note: 'No link here.' },
        ],
        affected_files: ['src/pages/Login.tsx'],
        confidence: 'high',
      },
      {
        requirement_id: 'R2',
        status: 'unclear',
        evidence: [],
        affected_files: [],
        confidence: 'low',
      },
    ],
    files_read: ['src/pages/Login.tsx'],
    drafts: [
      { draft: draft('T1'), edited: false, jira_key: null, jira_url: null },
      { draft: draft('T2'), edited: false, jira_key: null, jira_url: null },
    ],
    created: [],
    tokens_used: 12345,
    jira_labels: ['mtj-r1', 'mtj-r1-<draft id>'],
    sprint: null,
    review_stage: 'drafts',
    code_fit: {
      ok: true,
      verdict: 'matches',
      reason: 'Same app.',
      confident: 1,
      total: 2,
      files_read: 1,
    },
    ...overrides,
  };
}

const ROUTE = { route: '/runs/r1', path: '/runs/:runId' };

it('edits, saves and approves drafts with a confirmation', async () => {
  const fetch = mockFetch({
    'GET /api/runs/r1': () => json(detail()),
    'PUT /api/runs/r1/drafts': () => json([]),
    'POST /api/runs/r1/approve': () => json({ ...detail().run, status: 'creating_tickets' }, 202),
    'GET /api/jira/projects/DEMO/sprints': () =>
      json([{ id: 6, name: 'A3 Sprint 1', state: 'active', board: 'A3 board' }]),
  });
  const user = userEvent.setup();
  renderWithProviders(<RunDetailPage />, ROUTE);

  expect(await screen.findByText('Design review')).toBeInTheDocument();
  expect(sources.instances[0].url).toBe('/api/runs/r1/events');
  expect(screen.getByText('2 of 2 tickets selected')).toBeInTheDocument();
  // The unclear, low-confidence finding is flagged on its draft.
  expect(
    screen.getByText('The code could not confirm the state of this work.'),
  ).toBeInTheDocument();

  const approve = screen.getByRole('button', { name: 'Approve & create in Jira' });
  const title = screen.getAllByLabelText('Title')[0];
  await user.clear(title);
  await user.type(title, 'Add forgot password link');
  expect(approve).toBeDisabled();
  expect(screen.getByText('Save your edits before approving.')).toBeInTheDocument();

  await user.click(screen.getByRole('checkbox', { name: 'Include T2' }));
  expect(screen.getByText('1 of 2 tickets selected')).toBeInTheDocument();

  await user.click(screen.getByRole('button', { name: 'Save edits (1)' }));
  await waitFor(() => expect(approve).toBeEnabled());
  const put = fetch.mock.calls.find(([, init]) => init?.method === 'PUT')!;
  const saved = JSON.parse(put[1]!.body as string) as { drafts: TicketDraft[] };
  expect(saved.drafts).toHaveLength(1);
  expect(saved.drafts[0]).toMatchObject({ temp_id: 'T1', title: 'Add forgot password link' });

  await user.click(approve);
  const dialog = screen.getByRole('dialog', { name: 'Create Jira issues?' });
  await waitFor(() =>
    expect(
      within(dialog).getByRole('option', { name: 'A3 Sprint 1 (active)' }),
    ).toBeInTheDocument(),
  );
  await user.selectOptions(within(dialog).getByLabelText('Sprint'), '6');
  expect(dialog).toHaveTextContent('This creates 1 issue in Jira project DEMO.');
  expect(dialog).toHaveTextContent('mtj-r1');
  await user.click(within(dialog).getByRole('button', { name: 'Create issues' }));

  await waitFor(() =>
    expect(fetch.mock.calls.some(([url]) => url === '/api/runs/r1/approve')).toBe(true),
  );
  const post = fetch.mock.calls.find(([url]) => url === '/api/runs/r1/approve')!;
  expect(JSON.parse(post[1]!.body as string)).toEqual({ selected: ['T1'], sprint_id: 6 });
});

it('shows the code analysis with evidence and warnings', async () => {
  mockFetch({ 'GET /api/runs/r1': () => json(detail()) });
  const user = userEvent.setup();
  renderWithProviders(<RunDetailPage />, ROUTE);

  await user.click(await screen.findByRole('tab', { name: 'Code analysis' }));
  const panel = screen.getByRole('tabpanel');
  expect(within(panel).getByText('src/pages/Login.tsx:28-35')).toBeInTheDocument();
  expect(within(panel).getByText('No link here.')).toBeInTheDocument();
  expect(within(panel).getByText('unclear')).toBeInTheDocument();
  expect(within(panel).getByText('Check by hand')).toBeInTheDocument();

  await user.click(screen.getByRole('tab', { name: 'Summary by screen' }));
  expect(screen.getByText('Does the toggle exist?')).toBeInTheDocument();
  expect(screen.getByText('screen unclear')).toBeInTheDocument();
  expect(screen.getByRole('img', { name: 'Login' })).toHaveAttribute(
    'src',
    '/api/runs/r1/screenshots/1',
  );
});

it('shows live progress events and refreshes the run', async () => {
  const fetch = mockFetch({ 'GET /api/runs/r1': () => json(detail()) });
  renderWithProviders(<RunDetailPage />, ROUTE);
  await screen.findByText('Design review');
  const callsBefore = fetch.mock.calls.length;

  act(() =>
    sources.instances[0].emit('progress', {
      id: 7,
      run_id: 'r1',
      ts: '2026-11-09T10:00:05.000+00:00',
      step: 'draft_tickets',
      level: 'info',
      message: 'Drafting tickets: done in 1.0s. 2 draft tickets',
    }),
  );
  expect(await screen.findByText(/Drafting tickets: done/)).toBeInTheDocument();
  await waitFor(() => expect(fetch.mock.calls.length).toBeGreaterThan(callsBefore));
});

it('shows created issues and failures after completion', async () => {
  mockFetch({
    'GET /api/runs/r1': () =>
      json(
        detail({
          run: { ...detail().run, status: 'completed' },
          created: [
            {
              temp_id: 'T1',
              key: 'DEMO-1',
              url: 'https://jira/browse/DEMO-1',
              existed: false,
              error: null,
            },
            { temp_id: 'T2', key: null, url: null, existed: false, error: 'Field required' },
          ],
        }),
      ),
  });
  renderWithProviders(<RunDetailPage />, ROUTE);
  const link = await screen.findByRole('link', { name: /DEMO-1/ });
  expect(link).toHaveAttribute('href', 'https://jira/browse/DEMO-1');
  expect(screen.getByText('Field required')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Approve & create in Jira' })).toBeNull();
});

it('offers a retry for a failed run', async () => {
  const fetch = mockFetch({
    'GET /api/runs/r1': () =>
      json(
        detail({
          run: { ...detail().run, status: 'failed', error: 'Token budget reached' },
          drafts: [],
        }),
      ),
    'POST /api/runs/r1/retry': () => json({ ...detail().run, status: 'running' }, 202),
  });
  const user = userEvent.setup();
  renderWithProviders(<RunDetailPage />, ROUTE);
  expect(await screen.findByText('Token budget reached')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Retry from last step' }));
  await waitFor(() =>
    expect(fetch.mock.calls.some(([url]) => url === '/api/runs/r1/retry')).toBe(true),
  );
  await waitFor(() => expect(sources.instances).toHaveLength(2)); // stream reopened
});

it('stops before drafting when the code does not fit, and offers a re-run', async () => {
  const stopped = detail({
    drafts: [],
    review_stage: 'code_fit',
    code_fit: {
      ok: false,
      verdict: 'does_not_match',
      reason: 'The meeting is about a mobile onboarding flow; this is a web admin app.',
      confident: 0,
      total: 14,
      files_read: 21,
    },
  });
  const fetch = mockFetch({
    'GET /api/runs/r1': () => json(stopped),
    'GET /api/code/repos': () =>
      json([
        { id: 'fixtures/demo-app', name: 'fixtures/demo-app', default_branch: 'main' },
        { id: 'me/mobile-app', name: 'me/mobile-app', default_branch: 'develop' },
      ]),
    'GET /api/code/repos/me/mobile-app/branches': () => json(['develop', 'main']),
    'POST /api/runs/r1/rerun': () => json({ run_id: 'r2' }, 202),
    'POST /api/runs/r1/code-fit': () => json({ ...stopped.run, status: 'running' }, 202),
  });
  const user = userEvent.setup();
  renderWithProviders(<RunDetailPage />, ROUTE);

  const panel = await screen.findByRole('region', { name: 'Code check' });
  expect(panel).toHaveTextContent('No tickets were drafted');
  expect(panel).toHaveTextContent('does not seem to be the code this meeting is about');
  expect(panel).toHaveTextContent('mobile onboarding flow');
  expect(panel).toHaveTextContent('0 of 14 requirements could be checked with confidence');
  expect(screen.queryByRole('button', { name: 'Approve & create in Jira' })).toBeNull();
  // The analysis stays visible; the current repository is not offered again.
  expect(screen.getByRole('tab', { name: 'Code analysis' })).toHaveAttribute(
    'aria-selected',
    'true',
  );
  const repoSelect = within(panel).getByLabelText('Repository');
  await waitFor(() => expect(repoSelect).toHaveValue('me/mobile-app'));
  expect(within(repoSelect).queryByRole('option', { name: 'fixtures/demo-app' })).toBeNull();
  await waitFor(() => expect(within(panel).getByLabelText('Branch')).toHaveValue('develop'));

  await user.click(within(panel).getByRole('button', { name: 'Draft tickets anyway' }));
  await waitFor(() =>
    expect(fetch.mock.calls.some(([url]) => url === '/api/runs/r1/code-fit')).toBe(true),
  );
  const decision = fetch.mock.calls.find(([url]) => url === '/api/runs/r1/code-fit')!;
  expect(JSON.parse(decision[1]!.body as string)).toEqual({ decision: 'draft_anyway' });

  await user.click(within(panel).getByRole('button', { name: 'Re-run with this repository' }));
  await waitFor(() =>
    expect(fetch.mock.calls.some(([url]) => url === '/api/runs/r1/rerun')).toBe(true),
  );
  const rerun = fetch.mock.calls.find(([url]) => url === '/api/runs/r1/rerun')!;
  expect(JSON.parse(rerun[1]!.body as string)).toEqual({
    repo: 'me/mobile-app',
    branch: 'develop',
  });
});
