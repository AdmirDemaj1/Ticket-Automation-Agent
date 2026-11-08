import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { AuthProvider } from '@/auth/AuthProvider';

export function renderWithProviders(
  ui: ReactElement,
  {
    route = '/under-test',
    withAuth = false,
    path = '/under-test',
  }: { route?: string; withAuth?: boolean; path?: string } = {},
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const tree = (
    <Routes>
      <Route path={path} element={ui} />
      <Route path="/connections" element={<p>connections page</p>} />
      <Route path="/" element={<p>home page</p>} />
    </Routes>
  );
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        {withAuth ? <AuthProvider>{tree}</AuthProvider> : tree}
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
