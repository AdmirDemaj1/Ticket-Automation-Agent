import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { json, mockFetch } from '@/test/fetch-mock';
import { renderWithProviders } from '@/test/render';
import { NewRunPage } from './NewRunPage';

const TEXT = 'Anna: Add CSV export.\nMarco: Agreed.';

function routes(extra: Record<string, Parameters<typeof mockFetch>[0][string]> = {}) {
  return mockFetch({
    'GET /api/config/status': () =>
      json({
        llm: { provider: 'fake', model: 'm', api_key_set: false, max_tokens_per_run: 300000 },
        code: { provider: 'fake', base_url: null },
        jira: { provider: 'fake', base_url: null },
        limits: {
          max_code_files: 60,
          max_file_bytes: 200000,
          max_screenshots: 10,
          max_screenshot_bytes: 8000000,
        },
      }),
    'GET /api/code/repos': () =>
      json([{ id: 'fixtures/demo-app', name: 'demo-app (fixture)', default_branch: 'main' }]),
    'GET /api/code/repos/fixtures/demo-app/branches': () => json(['dev', 'main']),
    'GET /api/jira/projects': () => json([{ key: 'DEMO', name: 'Demo' }]),
    'GET /api/jira/projects/DEMO/issue-types': () =>
      json([
        { id: '1', name: 'Story', subtask: false },
        { id: '2', name: 'Task', subtask: false },
        { id: '3', name: 'Bug', subtask: false },
        { id: '4', name: 'Sub-task', subtask: true },
      ]),
    [`GET /api/runs/estimate?transcript_chars=${TEXT.length}&screenshots=0`]: () =>
      json({ tokens: 25000, max_tokens_per_run: 300000 }),
    [`GET /api/runs/estimate?transcript_chars=${TEXT.length}&screenshots=2`]: () =>
      json({ tokens: 28200, max_tokens_per_run: 300000 }),
    'GET /api/jira/projects/DEMO/sprints': () =>
      json([{ id: 6, name: 'DEMO Sprint 1', state: 'active', board: 'DEMO board' }]),
    'POST /api/runs': () => json({ run_id: 'r1' }, 202),
    ...extra,
  });
}

beforeEach(() => {
  // jsdom has no object URLs; the page only needs them for previews.
  URL.createObjectURL = vi.fn(() => 'blob:preview');
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => vi.unstubAllGlobals());

async function fillBasics() {
  // applyAccept off: the test also checks the page's own type check.
  const user = userEvent.setup({ applyAccept: false });
  await user.click(screen.getByRole('radio', { name: 'Paste text' }));
  fireEvent.change(screen.getByLabelText('Transcript text'), { target: { value: TEXT } });
  await waitFor(() => expect(screen.getByLabelText('Branch')).toHaveValue('main'));
  return user;
}

it('starts a run with pasted text and the chosen targets', async () => {
  const fetch = routes();
  renderWithProviders(<NewRunPage />);
  const user = await fillBasics();

  expect(await screen.findByText(/25,000 tokens/)).toBeInTheDocument();
  expect(screen.getByText(/sent to the Claude API/)).toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole('checkbox', { name: 'Story' })).toBeChecked());
  expect(screen.getByRole('checkbox', { name: 'Sub-task' })).not.toBeChecked();
  await user.click(screen.getByRole('checkbox', { name: 'Bug' }));
  await screen.findByRole('option', { name: 'DEMO Sprint 1 (active, DEMO board)' });
  await user.selectOptions(screen.getByLabelText('Sprint (optional)'), '6');
  await user.click(screen.getByRole('checkbox', { name: /I am allowed to share them/ }));
  await user.click(screen.getByRole('button', { name: 'Start' }));

  await waitFor(() =>
    expect(fetch.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(true),
  );
  const post = fetch.mock.calls.find(([, init]) => init?.method === 'POST')!;
  const body = post[1]!.body as FormData;
  expect(JSON.parse(body.get('inputs') as string)).toEqual({
    repo: 'fixtures/demo-app',
    branch: 'main',
    jira_project_key: 'DEMO',
    issue_types: ['Story', 'Task'],
    sprint_id: 6,
  });
  expect(body.get('transcript_text')).toBe(TEXT);
  expect(body.get('transcript_file')).toBeNull();
  expect(body.get('captions')).toBe('[]');
  expect(await screen.findByText('other page')).toBeInTheDocument(); // went to /runs/r1
});

it('lists what is missing instead of submitting', async () => {
  const fetch = routes();
  const user = userEvent.setup();
  renderWithProviders(<NewRunPage />);
  await screen.findByRole('option', { name: 'demo-app (fixture)' });
  await user.click(screen.getByRole('button', { name: 'Start' }));

  const alert = screen.getByRole('alert');
  expect(alert).toHaveTextContent('Add a transcript file or paste the transcript text.');
  expect(alert).toHaveTextContent('Confirm that the data may be sent to the Claude API.');
  expect(fetch.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false);
});

it('sends screenshots in the reordered order with their captions', async () => {
  const fetch = routes();
  renderWithProviders(<NewRunPage />);
  const user = await fillBasics();

  const login = new File(['a'], '01-login.png', { type: 'image/png' });
  const dash = new File(['b'], '02-dashboard.png', { type: 'image/png' });
  const notImage = new File(['c'], 'notes.gif', { type: 'image/gif' });
  await user.upload(screen.getByLabelText('Add screenshots'), [login, dash, notImage]);
  expect(screen.getByRole('alert')).toHaveTextContent('notes.gif: not PNG, JPEG or WebP');

  const list = screen.getByRole('list', { name: 'Screenshots in order' });
  expect(within(list).getAllByRole('listitem')).toHaveLength(2);
  expect(screen.getByLabelText('Caption for 01-login.png')).toHaveValue('login');
  await user.click(screen.getByRole('button', { name: 'Move 01-login.png down' }));
  const caption = screen.getByLabelText('Caption for 02-dashboard.png');
  await user.clear(caption);
  await user.type(caption, 'Orders dashboard');

  await user.click(screen.getByRole('checkbox', { name: /I am allowed to share them/ }));
  await user.click(screen.getByRole('button', { name: 'Start' }));
  await waitFor(() =>
    expect(fetch.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(true),
  );
  const body = fetch.mock.calls.find(([, init]) => init?.method === 'POST')![1]!.body as FormData;
  expect((body.getAll('screenshots') as File[]).map((f) => f.name)).toEqual([
    '02-dashboard.png',
    '01-login.png',
  ]);
  expect(JSON.parse(body.get('captions') as string)).toEqual(['Orders dashboard', 'login']);
});

it('shows a server error from starting the run', async () => {
  routes({ 'POST /api/runs': () => json({ detail: 'Branch not found' }, 400) });
  renderWithProviders(<NewRunPage />);
  const user = await fillBasics();
  await user.click(screen.getByRole('checkbox', { name: /I am allowed to share them/ }));
  await user.click(screen.getByRole('button', { name: 'Start' }));
  expect(await screen.findByText(/Could not start the run: Branch not found/)).toBeInTheDocument();
});
