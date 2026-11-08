import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import { json, mockFetch, session } from '@/test/fetch-mock';
import { renderWithProviders } from '@/test/render';
import { RegisterPage } from './RegisterPage';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it('requires a 12+ character password', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  mockFetch({ 'POST /api/auth/refresh': () => json({}, 401) });
  renderWithProviders(<RegisterPage />, { withAuth: true, route: '/register', path: '/register' });

  await userEvent.type(await screen.findByLabelText('Name'), 'Ada');
  await userEvent.type(screen.getByLabelText('Email'), 'ada@example.com');
  await userEvent.type(screen.getByLabelText('Password'), 'short');
  await userEvent.click(screen.getByRole('button', { name: 'Create account' }));

  expect(await screen.findByText('Use at least 12 characters')).toBeInTheDocument();
});

it('registers and goes to connections', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  mockFetch({
    'POST /api/auth/refresh': () => json({}, 401),
    'POST /api/auth/register': () => json(session(), 201),
  });
  renderWithProviders(<RegisterPage />, { withAuth: true, route: '/register', path: '/register' });

  await userEvent.type(await screen.findByLabelText('Name'), 'Ada');
  await userEvent.type(screen.getByLabelText('Email'), 'ada@example.com');
  await userEvent.type(screen.getByLabelText('Password'), 'a long enough password');
  await userEvent.click(screen.getByRole('button', { name: 'Create account' }));

  expect(await screen.findByText('connections page')).toBeInTheDocument();
});
