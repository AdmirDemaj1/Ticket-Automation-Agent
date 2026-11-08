import { Route, Routes } from 'react-router-dom';
import { HomePage } from '@/pages/HomePage';

export function App() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-border px-6 py-3 font-semibold">Meeting → Jira</header>
      <main className="p-6">
        <Routes>
          <Route path="/" element={<HomePage />} />
        </Routes>
      </main>
    </div>
  );
}
