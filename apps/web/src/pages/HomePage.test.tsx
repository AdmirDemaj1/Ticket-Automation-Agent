import { screen } from '@testing-library/react';
import { afterEach, vi } from 'vitest';
import { renderWithProviders } from '@/test/render';
import { HomePage } from './HomePage';

afterEach(() => vi.unstubAllGlobals());

it('shows healthy status', async () => {
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ status: 'ok', db: 'ok' }), { status: 200 })),
  );
  renderWithProviders(<HomePage />);
  expect(await screen.findByText('API ok, DB ok')).toBeInTheDocument();
});

it('shows an error when the API is down', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 503 })));
  renderWithProviders(<HomePage />);
  expect(await screen.findByText('API unreachable')).toBeInTheDocument();
});
