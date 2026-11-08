import type { ConnectionView } from '@mtj/contracts';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import { json, mockFetch } from '@/test/fetch-mock';
import { renderWithProviders } from '@/test/render';
import { ConnectionsPage } from './ConnectionsPage';

afterEach(() => vi.unstubAllGlobals());

const view = (
  provider: ConnectionView['provider'],
  state: ConnectionView['state'],
): ConnectionView => ({
  provider,
  state,
  externalAccountId: state === 'not_connected' ? null : `${provider}-acct`,
  scopes: [],
  expiresAt: null,
  connectedAt: null,
});

it('shows every provider with its state', async () => {
  mockFetch({
    'GET /api/connections': () =>
      json([
        view('jira', 'connected'),
        view('github', 'needs_reauth'),
        view('gitlab', 'not_connected'),
        view('msgraph', 'not_connected'),
        view('spinach', 'not_connected'),
      ]),
  });
  renderWithProviders(<ConnectionsPage />);

  const items = await screen.findAllByRole('listitem');
  expect(items).toHaveLength(5);
  expect(within(items[0]).getByText('Connected')).toBeInTheDocument();
  expect(within(items[0]).getByText('Account: jira-acct')).toBeInTheDocument();
  expect(within(items[1]).getByText('Reconnect needed')).toBeInTheDocument();
  expect(within(items[2]).getByRole('button', { name: /connect \(coming soon\)/i })).toBeDisabled();
});

it('disconnects and reloads the list', async () => {
  let connected = true;
  const fetch = mockFetch({
    'GET /api/connections': () => json([view('jira', connected ? 'connected' : 'not_connected')]),
    'DELETE /api/connections/jira': () => {
      connected = false;
      return new Response(null, { status: 204 });
    },
  });
  renderWithProviders(<ConnectionsPage />);

  await userEvent.click(await screen.findByRole('button', { name: 'Disconnect Jira' }));
  expect(await screen.findByText('Not connected')).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledWith(
    '/api/connections/jira',
    expect.objectContaining({ method: 'DELETE' }),
  );
});

it('shows an error state', async () => {
  mockFetch({ 'GET /api/connections': () => json({ message: 'boom' }, 500) });
  renderWithProviders(<ConnectionsPage />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not load connections: boom');
});
