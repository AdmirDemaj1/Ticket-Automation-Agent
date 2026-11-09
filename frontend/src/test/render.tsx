import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

export function renderWithProviders(
  ui: ReactElement,
  { route = '/under-test', path = '/under-test' }: { route?: string; path?: string } = {},
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const tree = (
    <Routes>
      <Route path={path} element={ui} />
      <Route path="/" element={<p>runs page</p>} />
      <Route path="*" element={<p>other page</p>} />
    </Routes>
  );
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>{tree}</MemoryRouter>
    </QueryClientProvider>,
  );
}
