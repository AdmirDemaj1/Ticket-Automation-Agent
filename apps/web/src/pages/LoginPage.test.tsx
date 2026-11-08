import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import { json, mockFetch, session } from '@/test/fetch-mock';
import { renderWithProviders } from '@/test/render';
import { LoginPage } from './LoginPage';

afterEach(() => vi.unstubAllGlobals());

const anonymous = { 'POST /api/auth/refresh': () => json({}, 401) };

it('validates fields before calling the API', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const fetch = mockFetch(anonymous);
  renderWithProviders(<LoginPage />, { withAuth: true, route: '/login', path: '/login' });
  await userEvent.click(await screen.findByRole('button', { name: 'Log in' }));

  expect(await screen.findByText('Enter a valid email')).toBeInTheDocument();
  expect(screen.getByText('Password is required')).toBeInTheDocument();
  expect(screen.getByLabelText('Email')).toHaveAttribute('aria-invalid', 'true');
  expect(fetch.mock.calls.every(([url]) => url === '/api/auth/refresh')).toBe(true);
  vi.useRealTimers();
});

it('logs in with a normalized email and redirects home', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  let body: unknown;
  mockFetch({
    ...anonymous,
    'POST /api/auth/login': (init) => {
      body = JSON.parse(init!.body as string);
      return json(session());
    },
  });
  renderWithProviders(<LoginPage />, { withAuth: true, route: '/login', path: '/login' });

  await userEvent.type(await screen.findByLabelText('Email'), '  Ada@Example.com ');
  await userEvent.type(screen.getByLabelText('Password'), 'pw');
  await userEvent.click(screen.getByRole('button', { name: 'Log in' }));

  expect(await screen.findByText('home page')).toBeInTheDocument();
  expect(body).toEqual({ email: 'ada@example.com', password: 'pw' });
  vi.useRealTimers();
});

it('shows the server error on bad credentials', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  mockFetch({
    ...anonymous,
    'POST /api/auth/login': () => json({ message: 'Invalid email or password' }, 401),
  });
  renderWithProviders(<LoginPage />, { withAuth: true, route: '/login', path: '/login' });

  await userEvent.type(await screen.findByLabelText('Email'), 'ada@example.com');
  await userEvent.type(screen.getByLabelText('Password'), 'wrong');
  await userEvent.click(screen.getByRole('button', { name: 'Log in' }));

  expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password');
  vi.useRealTimers();
});
