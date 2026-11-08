import { screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { Run } from '@/lib/types';
import { json, mockFetch } from '@/test/fetch-mock';
import { renderWithProviders } from '@/test/render';
import { RunsPage } from './RunsPage';

afterEach(() => vi.unstubAllGlobals());

it('shows an empty state', async () => {
  mockFetch({ 'GET /api/runs': () => json([]) });
  renderWithProviders(<RunsPage />);
  expect(await screen.findByText(/No runs yet/)).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'New run' })).toHaveAttribute('href', '/runs/new');
});

it('lists runs', async () => {
  const run: Run = {
    id: 'r1',
    status: 'awaiting_review',
    inputs: {
      repo: 'fixtures/demo-app',
      branch: 'main',
      jira_project_key: 'DEMO',
      issue_types: ['Story'],
      sprint_id: null,
    },
    error: null,
    created_at: '2026-11-08T10:00:00.000+00:00',
    updated_at: '2026-11-08T10:05:00.000+00:00',
  };
  mockFetch({ 'GET /api/runs': () => json([run]) });
  renderWithProviders(<RunsPage />);
  expect(await screen.findByText('fixtures/demo-app @ main')).toBeInTheDocument();
  expect(screen.getByText('DEMO')).toBeInTheDocument();
  expect(screen.getByText('awaiting review')).toBeInTheDocument();
});

it('shows a load error', async () => {
  mockFetch({ 'GET /api/runs': () => json({ detail: 'database locked' }, 500) });
  renderWithProviders(<RunsPage />);
  expect(await screen.findByRole('alert')).toHaveTextContent('database locked');
});
