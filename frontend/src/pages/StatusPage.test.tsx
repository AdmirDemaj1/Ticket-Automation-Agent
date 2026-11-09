import { screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { ConfigStatus } from '@/lib/types';
import { json, mockFetch } from '@/test/fetch-mock';
import { renderWithProviders } from '@/test/render';
import { StatusPage } from './StatusPage';

afterEach(() => vi.unstubAllGlobals());

const config: ConfigStatus = {
  llm: {
    provider: 'fake',
    model: 'claude-opus-5-5',
    api_key_set: false,
    max_tokens_per_run: 300000,
  },
  code: { provider: 'fake', base_url: null },
  jira: { provider: 'fake', base_url: null },
  limits: {
    max_code_files: 60,
    max_file_bytes: 200000,
    max_screenshots: 10,
    max_screenshot_bytes: 8000000,
  },
};

it('shows backend health and provider configuration', async () => {
  mockFetch({
    'GET /api/healthz': () => json({ status: 'ok' }),
    'GET /api/config/status': () => json(config),
  });
  renderWithProviders(<StatusPage />);

  expect(await screen.findByText('Backend running')).toBeInTheDocument();
  expect(await screen.findByText('claude-opus-5-5')).toBeInTheDocument();
  expect(screen.getByText('No API key')).toBeInTheDocument();
  expect(screen.getAllByText('fake')).toHaveLength(2);
});

it('shows errors when the backend is down', async () => {
  mockFetch({
    'GET /api/healthz': () => json({}, 503),
    'GET /api/config/status': () => json({ detail: 'boom' }, 500),
  });
  renderWithProviders(<StatusPage />);

  expect(await screen.findByText('Backend unreachable')).toBeInTheDocument();
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not load configuration: boom');
});
