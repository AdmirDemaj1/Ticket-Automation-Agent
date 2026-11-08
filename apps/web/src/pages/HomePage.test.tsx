import { screen } from '@testing-library/react';
import { afterEach, vi } from 'vitest';
import { json, mockFetch } from '@/test/fetch-mock';
import { renderWithProviders } from '@/test/render';
import { HomePage } from './HomePage';

afterEach(() => vi.unstubAllGlobals());

it('shows healthy status', async () => {
  mockFetch({ 'GET /api/healthz': () => json({ status: 'ok', db: 'ok' }) });
  renderWithProviders(<HomePage />);
  expect(await screen.findByText('API ok, DB ok')).toBeInTheDocument();
});

it('shows an error when the API is down', async () => {
  mockFetch({ 'GET /api/healthz': () => json({}, 503) });
  renderWithProviders(<HomePage />);
  expect(await screen.findByText('API unreachable')).toBeInTheDocument();
});
